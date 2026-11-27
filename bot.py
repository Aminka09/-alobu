import os
import time
import json
import requests
import subprocess

# ==========================================
# 1. КОНФИГУРАЦИЯ И ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
# ==========================================
# Эти значения должны быть заданы в GitHub Secrets или в начале файла
TG_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "ТВОЙ_ТОКЕН")
TG_CHAT_ID = os.getenv("CHAT_ID", "ТВОЙ_CHAT_ID")
RAW_COOKIE = os.getenv("RAW_COOKIE", "")  # Обязательно добавь в Secrets!

# URL и заголовки (заполни своими данными, если они были в старом коде)
REPORTS_URL = "https://example.com/api/reports"  # <-- ВСТАВЬ СЮДА СВОЙ URL
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

MAX_RUN_MINUTES = 55
STATE_FILE = "last_report_id.json"
ADMIN_LINK = "https://example.com/admin"  # <-- ВСТАВЬ СЮДА ССЫЛКУ НА АДМИНКУ

# ==========================================
# 2. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (из твоего кода)
# ==========================================

def load_last_id():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return int(data.get("last_id", 0))
    except Exception:
        return 0

def save_last_id(report_id):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_id": report_id}, f, ensure_ascii=False)
    commit_state_file()

def commit_state_file():
    """Коммитит файл состояния обратно в репозиторий, чтобы сохранить last_id"""
    try:
        env = os.environ.copy()
        # Настройка автора коммита для GitHub Actions
        subprocess.run(["git", "config", "user.name", "github-actions"], check=False)
        subprocess.run(["git", "config", "user.email", "actions@github.com"], check=False)
        
        subprocess.run(["git", "add", STATE_FILE], check=False)
        
        # Коммитим только если есть изменения
        r = subprocess.run(["git", "diff", "--staged", "--quiet", STATE_FILE], check=False)
        if r.returncode == 0:
            return # Изменений нет
            
        subprocess.run(
            ["git", "commit", "-m", f"Update {STATE_FILE} via workflow at {time.strftime('%Y-%m-%d %H:%M:%S')}"],
            check=False, env=env
        )
        subprocess.run(["git", "push"], check=False, env=env)
    except Exception as e:
        print(f"[WARN] Не удалось закоммитить файл состояния: {e}")

def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def extract_id(item):
    for key in ("id", "complaint_id", "report_id"):
        if key in item:
            try:
                return int(item[key])
            except (TypeError, ValueError):
                continue
    return None

# ==========================================
# 3. ОСНОВНЫЕ ФУНКЦИИ ЛОГИКИ (из твоего кода)
# ==========================================

def send_tg(text):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[TG] Ошибка отправки: {e}")
        return False

def notify_session_expired():
    msg = (
        "⚠️ <b>Сессия истекла!</b>\n\n"
        "Кука для скрипта больше не работает.\n"
        f"Зайди в админку через браузер и обнови секрет <code>RAW_COOKIE</code> в GitHub Secrets.\n"
        f"Ссылка: {ADMIN_LINK}"
    )
    send_tg(msg)

def fetch_reports():
    """Получает сырые данные с сайта"""
    headers = dict(HEADERS)
    headers["Cookie"] = RAW_COOKIE
    
    try:
        r = requests.get(REPORTS_URL, headers=headers, timeout=20)
        if r.status_code in (401, 403):
            print(f"[WARN] Статус {r.status_code}: сессия истекла.")
            return None, r.status_code
        r.raise_for_status()
        return r.json(), r.status_code
    except Exception as e:
        print(f"[ERROR] Ошибка запроса: {e}")
        return None, 0

def normalize(data):
    """Пытается найти список жалоб внутри ответа"""
    if isinstance(data, list):
        return data
    
    for key in ("complaints", "data", "items", "reports", "result", "rows"):
        if isinstance(data, dict) and isinstance(data.get(key), list):
            return data[key]
    
    print("[WARN] Не смог найти список жалоб в ответе. Полный ответ (фрагмент):")
    print(json.dumps(data, ensure_ascii=False)[:500])
    return 

def format_report(item):
    """Формирует красивое сообщение для одной жалобы"""
    rid = extract_id(item)
    sender = esc(item.get("from_user_name", "Неизвестно"))
    target = esc(item.get("to_user_name", "Неизвестно"))
    server = item.get("server", "-")
    
    # Формируем ссылку на жалобу, если есть ID
    link = f"{ADMIN_LINK}/report/{rid}" if rid else ADMIN_LINK
    
    return (
        f"🆕 <b>Новая жалоба #{rid}</b>\n"
        f"👤 Подал: <b>{sender}</b>\n"
        f"🎯 На кого: <b>{target}</b>\n"
        f"🌐 Сервер: <code>{server}</code>\n"
        f"🔗 <a href='{link}'>Открыть в админке</a>"
    )

# ==========================================
# 4. ТОЧКА ВХОДА ДЛЯ GITHUB ACTIONS
# ==========================================

def run_once():
    """
    Главная функция для GitHub Actions.
    Делает ОДНУ проверку, отправляет уведомления и завершается.
    """
    print("[INFO] =========================================")
    print("[INFO] Запуск однократной проверки (GitHub Mode)")
    print("[INFO] =========================================")
    
    last_id = load_last_id()
    print(f"[INFO] Последний обработанный ID: {last_id}")
    
    # 1. Получаем данные
    raw_data, status = fetch_reports()
    
    if raw_data is None:
        print("[CRITICAL] Данные не получены. Проверка сессии...")
        notify_session_expired()
        return

    # 2. Нормализуем (ищем список)
    complaints_list = normalize(raw_data)
    
    if not complaints_list:
        print("[INFO] Список жалоб пуст или не найден.")
        return

    print(f"[INFO] Найдено всего жалоб в ответе: {len(complaints_list)}")
    
    new_complaints_count = 0
    
    # 3. Обрабатываем каждую жалобу
    for item in complaints_list:
        rid = extract_id(item)
        
        # Пропускаем старые, если у нас есть last_id
        if last_id and rid and rid <= last_id:
            continue
            
        # Если дошли сюда - это новая жалоба
        new_complaints_count += 1
        
        # Формируем и отправляем сообщение
        message = format_report(item)
        if send_tg(message):
            print(f"[OK] Отправлено уведомление для жалобы #{rid}")
        else:
            print(f"[ERR] Не удалось отправить сообщение для #{rid}")
        
        # Обновляем last_id сразу после успешной отправки (или просто обработки)
        if rid:
            save_last_id(rid)
            
        # ЛИМИТ: чтобы не спамить в Телеграм, если навалилось 100 жалоб разом
        # В реальном продакшене лучше отправлять пакетно, но пока ограничимся первыми 10
        if new_complaints_count >= 10:
            print("[WARN] Достигнут лимит отправки (10 шт). Остальные будут обработаны в следующем запуске.")
            break

    if new_complaints_count == 0:
        print("[INFO] Новых жалоб не найдено (все ID меньше или равны сохраненному).")
    else:
        print(f"[SUCCESS] Обработано новых жалоб: {new_complaints_count}")

    print("[INFO] Проверка завершена. Скрипт завершается.")

# ==========================================
# 5. ТОЧКА ВХОДА
# ==========================================

if __name__ == "__main__":
    # Для GitHub Actions используем run_once() вместо check_reports() с циклом while
    run_once()
