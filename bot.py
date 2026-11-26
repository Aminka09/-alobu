# -*- coding: utf-8 -*-
"""
Уведомления о новых жалобах grnd.gg -> Telegram.
Версия для GitHub Actions: скрипт сам крутится ~55 минут,
проверяя жалобы каждую минуту, а потом завершается.
Состояние (последний ID) сохраняется в репозиторий через git commit.

Секреты берутся из переменных окружения GitHub:
RAW_COOKIE, TG_BOT_TOKEN, TG_CHAT_ID
"""

import json
import os
import subprocess
import time
import requests

# ---------------- КОНФИГ ----------------

RAW_COOKIE = os.environ.get("RAW_COOKIE", "")
REPORTS_URL = os.environ.get(
    "REPORTS_URL",
    "https://grnd.gg/api/admin/complaints?status=0&server=%7B%22ru%22%3A%5B15%5D%7D",
)
ADMIN_LINK = os.environ.get("ADMIN_LINK", "https://grnd.gg/admin/complaints")

TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "ru,en;q=0.9",
}

CHECK_INTERVAL = 60                 # проверка каждую минуту
MAX_RUN_MINUTES = 55                # сколько минут живёт один запуск Actions
STATE_FILE = "last_report_id.json"

# -----------------------------------------


def load_last_id():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return int(json.load(f).get("last_id", 0))
    except Exception:
        return 0


def save_last_id(report_id):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_id": report_id}, f)
    commit_state_file()


def commit_state_file():
    """Коммитит файл состояния обратно в репозиторий, чтобы не потерять память."""
    try:
        env = os.environ.copy()
        # настроим автора коммита, если не задан
        subprocess.run(["git", "config", "user.name", "reports-bot"], check=False, env=env)
        subprocess.run(["git", "config", "user.email", "actions@localhost"], check=False, env=env)
        subprocess.run(["git", "add", STATE_FILE], check=False, env=env)
        # коммитим только если есть изменения
        r = subprocess.run(["git", "diff", "--cached", "--quiet"], env=env)
        if r.returncode == 0:
            return  # изменений нет
        subprocess.run(
            ["git", "commit", "-m", f"chore: update last_report_id ({report_id_time()})"],
            check=False, env=env,
        )
        subprocess.run(["git", "push"], check=False, env=env)
    except Exception as e:
        print(f"[GIT] Не удалось закоммитить состояние: {e}")


def report_id_time():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def send_tg(text):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML",
               "disable_web_page_preview": True}
    try:
        r = requests.post(url, json=payload, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"[TG] Ошибка отправки: {e}")


def notify_session_expired():
    send_tg(
        "⚠️ <b>Сессия истекла!</b>\n"
        "Кука для скрипта больше не работает.\n"
        "Зайди в админку через браузер, скопируй новую строку Cookie\n"
        "и обнови секрет RAW_COOKIE в репозитории."
    )


def fetch_reports():
    headers = dict(HEADERS)
    headers["Cookie"] = RAW_COOKIE
    r = requests.get(REPORTS_URL, headers=headers, timeout=20)
    if r.status_code in (401, 403):
        return None, r.status_code
    r.raise_for_status()
    return r.json(), r.status_code


def normalize(data):
    if isinstance(data, list):
        return data
    for key in ("complaints", "data", "items", "reports", "result", "rows"):
        if isinstance(data, dict) and isinstance(data.get(key), list):
            return data[key]
    print("[WARN] Не смог найти список жалоб в ответе. Полный ответ:")
    print(json.dumps(data, ensure_ascii=False)[:2000])
    return []


def extract_id(item):
    for key in ("id", "complaint_id", "report_id", "ID", "_id"):
        if key in item:
            try:
                return int(item[key])
            except (TypeError, ValueError):
                continue
    return None


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_report(item):
    rid = extract_id(item)
    sender = esc(item.get("from_user_name") or "—")
    target = esc(item.get("to_user_name") or "—")
    server = item.get("server") or "—"
    return (
        f"🆕 <b>Новая жалоба #{rid}</b> (сервер {esc(server)})\n"
        f"👤 Подал: <b>{sender}</b>\n"
        f"🎯 На кого: <b>{target}</b>\n"
        f"🔗 {ADMIN_LINK}"
    )


def main_loop():
    if not RAW_COOKIE or not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("❌ Не заданы секреты RAW_COOKIE / TG_BOT_TOKEN / TG_CHAT_ID!")
        return

    last_id = load_last_id()
    first_run = last_id == 0
    print(f"[OK] Запуск. Последний известный ID жалобы: {last_id}")

    notified_about_session = False
    deadline = time.time() + MAX_RUN_MINUTES * 60
    cycle = 0

    while time.time() < deadline:
        cycle += 1
        try:
            data, status = fetch_reports()
            if data is None:
                print(f"[!] Сессия мертва (код {status}).")
                if not notified_about_session:
                    notify_session_expired()
                    notified_about_session = True
                time.sleep(CHECK_INTERVAL)
                continue

            reports = normalize(data)

            if first_run:
                ids = [extract_id(it) for it in reports if extract_id(it) is not None]
                if ids:
                    last_id = max(ids)
                    save_last_id(last_id)
                    first_run = False
                    print(f"[OK] Первый запуск: запомнил {len(ids)} жалоб, максимум ID={last_id}.")
                time.sleep(CHECK_INTERVAL)
                continue

            new_items = [
                it for it in reports
                if extract_id(it) is not None and extract_id(it) > last_id
            ]

            if new_items:
                new_items.sort(key=extract_id)
                for item in new_items:
                    rid = extract_id(item)
                    send_tg(format_report(item))
                    last_id = max(last_id, rid)
                    save_last_id(last_id)
                    time.sleep(2)
                print(f"[OK] Отправлено новых жалоб: {len(new_items)} (макс ID={last_id})")
            else:
                print(f"[..] Цикл {cycle}: новых жалоб нет (в списке: {len(reports)})")

        except requests.exceptions.HTTPError as e:
            print(f"[HTTP] {e}")
        except Exception as e:
            print(f"[ERR] {e}")

        time.sleep(CHECK_INTERVAL)

    print("[OK] Время запуска истекло, завершаюсь. Следующий запуск — по расписанию.")


if __name__ == "__main__":
    main_loop()
