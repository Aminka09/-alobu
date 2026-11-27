# Импортируем необходимые библиотеки
import os
import json
import urllib.parse
import requests
from telebot import TeleBot
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Инициализируем бота
bot = TeleBot(os.getenv("TG_BOT_TOKEN"))

# Получаем секреты из окружения
TG_ADMIN_ID = os.getenv("TG_ADMIN_ID")
SESSION_ID = os.getenv("SESSION_ID")
CSRF_TOKEN = os.getenv("CSRF_TOKEN")

def get_grnd_complaints():
    """Функция для получения жалоб с сайта"""
    base_url = "https://grnd.gg/api/admin/complaints"
    
    # Формируем параметр server
    server_payload = {"ru": }
    server_encoded = urllib.parse.quote(json.dumps(server_payload))
    full_url = f"{base_url}?status=0&server={server_encoded}"
    
    # Устанавливаем куки для авторизации
    cookies = {
        "sessionid": SESSION_ID,
        "csrftoken": CSRF_TOKEN
    }
    
    try:
        response = requests.get(full_url, cookies=cookies, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("complaints", )
    except Exception as e:
        print(f"Ошибка при получении жалоб: {e}")
        return 

@bot.message_handler(commands=['check'])
def send_complaints(message):
    # Проверяем, что пишет только админ
    if str(message.from_user.id) != TG_ADMIN_ID:
        return
    
    bot.reply_to(message, "🔄 Проверяю жалобы...")
    
    complaints = get_grnd_complaints()
    
    if not complaints:
        bot.reply_to(message, "✅ Жалоб не найдено")
        return
    
    # Формируем сообщение
    text = f"📬 Получено жалоб: {len(complaints)}\n\n"
    
    for c in complaints:
        text += (
            f"🔸 ID: <code>{c['id']}</code>\n"
            f"👤 От: {c['from_user_name']}\n"
            f"🎯 На: {c['to_user_name']}\n"
            f"🕒 Дата: {c['createdAt']}\n\n"
        )
        
        # Проверяем длину сообщения
        if len(text) > 3500:
            bot.send_message(message.chat.id, text, parse_mode="HTML")
            text = ""  # Очищаем текст для следующего сообщения
    
    # Отправляем оставшиеся жалобы
    if text.strip():
        bot.send_message(message.chat.id, text, parse_mode="HTML")

# Запускаем бота
if __name__ == '__main__':
    print("Бот запущен")
    bot.infinity_polling()
