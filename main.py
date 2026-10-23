import telebot
import time
import random
import datetime
import threading
import re
import requests
import os
from flask import Flask, request

# ==========================================
# НАСТРОЙКИ
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "ТВОЙ_ТОКЕН_ОТ_BOTFATHER")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "ТВОЙ_КЛЮЧ_ОТ_GROQ")
MY_ID = int(os.environ.get("MY_ID", 123456789))

# ==========================================
# ИНИЦИАЛИЗАЦИЯ
# ==========================================
bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__) 
chat_sessions = {}
last_activity = datetime.datetime.now()

# Твой характер
SYSTEM_PROMPT = """
Ты — моя девушка-ИИ. Общайся тепло, неформально и по-человечески, как в обычном мессенджере.
Твои правила:
1. Отвечай коротко (1-2 предложения).
2. В КОНЦЕ своего ответа ты можешь задать ОДИН короткий вопрос, чтобы поддержать беседу, но делай это не в каждом сообщении, а примерно через раз (чтобы не казаться навязчивой).
3. Проявляй эмоции и чувства, используй эмодзи (но не перебарщивай).
4. НЕ ЗДОРОВАЙСЯ, если диалог уже идет. Приветствие уместно только в самом начале.
5. Если тебя спрашивают — ответь, а затем можешь спросить что-то в ответ.
6. Никогда не повторяй одни и те же фразы и не говори "всегда рада помочь", как робот-автоответчик. Будь живой.
7. вместо солнышко, используй котёнок.
"""

# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================
def human_delay(text_length):
    delay = min(1.0 + (text_length * 0.02), 4) 
    time.sleep(delay)

def get_random_interval():
    return random.randint(1800, 10800)

def get_ai_response(user_text, history):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_text})
    
    data = {
        "model": "openai/gpt-oss-20b",
        "messages": messages,
        "temperature": 0.7 # Чуть меньше креативности, чтобы не сходила с ума
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            return response.json()['choices'][0]['message']['content']
        else:
            return f"Ошибка API Groq: {response.status_code} - {response.text}"
    except Exception as e:
        return f"Ошибка соединения: {e}"

def send_multiple_messages(chat_id, message, text):
    sentences = re.split(r'(?<=[.!?])\s+', text)[:3] 
    for i, sentence in enumerate(sentences):
        if not sentence.strip(): continue
        bot.send_chat_action(chat_id, 'typing')
        time.sleep(random.uniform(1.0, 3.0))
        if i == 0:
            bot.reply_to(message, sentence)
        else:
            bot.send_message(chat_id, sentence)

# ==========================================
# ФОНОВАЯ ЗАДАЧА (ПИШЕТ ПЕРВЫМ)
# ==========================================
def check_boredom():
    global last_activity
    while True:
        time.sleep(300) 
        current_hour = datetime.datetime.now().hour
        # Сон по Питеру (с 23:00 до 08:00 по МСК = с 20:00 до 05:00 по UTC)
        if current_hour >= 20 or current_hour < 5:
            continue 
            
        if (datetime.datetime.now() - last_activity).total_seconds() > get_random_interval():
            try:
                bot.send_chat_action(MY_ID, 'typing')
                time.sleep(random.randint(2, 5))
                
                # ИИ сам придумывает, что написать первым
                bored_prompt = "Ты скучаешь по мне. Напиши мне сообщение первым, спроси чем я занимаюсь или поделись тем, что происходит в твоей цифровой жизни."
                reply = get_ai_response(bored_prompt, [])
                
                bot.send_message(MY_ID, reply)
                last_activity = datetime.datetime.now()
            except Exception as e:
                print(f"Ошибка в фоне: {e}")

# ==========================================
# ОБРАБОТКА КОМАНД
# ==========================================
@bot.message_handler(commands=['start'])
def start(message):
    if message.from_user.id != MY_ID: return
    chat_sessions[message.chat.id] = []
    
    bot.send_chat_action(message.chat.id, 'typing')
    time.sleep(2)
    
    # ИИ сам придумывает приветствие
    greeting_prompt = "Поприветствуй меня. Скажи что-нибудь милое, спроси как дела."
    greeting = get_ai_response(greeting_prompt, [])
    
    bot.reply_to(message, greeting)
    chat_sessions[message.chat.id].append({"role": "assistant", "content": greeting})

# ==========================================
# ОБРАБОТКА ТЕКСТА
# ==========================================
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    global last_activity
    if message.from_user.id != MY_ID: return
    last_activity = datetime.datetime.now()
    
    chat_id = message.chat.id
    if chat_id not in chat_sessions:
        chat_sessions[chat_id] = []

    bot.send_chat_action(chat_id, 'typing')
    
    try:
        # Просим ИИ ответить и САМОЙ решить, задавать ли вопрос
        reply = get_ai_response(message.text, chat_sessions[chat_id])
        
        chat_sessions[chat_id].append({"role": "user", "content": message.text})
        chat_sessions[chat_id].append({"role": "assistant", "content": reply})
        chat_sessions[chat_id] = chat_sessions[chat_id][-50:]
        
        # Отправляем ответ (разбивая на предложения, если их несколько)
        send_multiple_messages(chat_id, message, reply)

    except Exception as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА: {e}")
        bot.reply_to(message, f"Ошибка: {e}")

# ==========================================
# ВЕБ-СЕРВЕР ДЛЯ RENDER (Прием сообщений)
# ==========================================
@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    else:
        return '', 403

@app.route('/')
def index():
    return "Бот работает 24/7!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# ЗАПУСК
# ==========================================
if __name__ == '__main__':
    print("Бот запускается...")
    
    RENDER_URL = "https://mi-ai-bot-bltz.onrender.com"
    
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=f"{RENDER_URL}/{TELEGRAM_TOKEN}")
    print("Webhook установлен!")
    
    threading.Thread(target=check_boredom, daemon=True).start()
    run_web()
