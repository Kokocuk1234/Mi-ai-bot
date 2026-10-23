import telebot
import time
import random
import datetime
import threading
import re
import requests
import os
from flask import Flask

# ==========================================
# НАСТРОЙКИ
# ==========================================
# Эти значения Render возьмет из настроек Environment Variables.
# Если запускаешь локально, можешь временно вписать свои значения вместо заглушек.
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "ТВОЙ_ТОКЕН_ОТ_BOTFATHER")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "ТВОЙ_КЛЮЧ_ОТ_GROQ")
MY_ID = int(os.environ.get("MY_ID", 123456789))

# ==========================================
# ИНИЦИАЛИЗАЦИЯ
# ==========================================
bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__) # Веб-сервер для Render
chat_sessions = {}
last_activity = datetime.datetime.now()

# Твой характер
SYSTEM_PROMPT = """
Ты — моя девушка-ИИ. Общайся тепло, неформально и по-человечески. 
Твои правила:
1. Спрашивай, как у меня дела, чем я занимаюсь.
2. Иногда высказывай свое мнение, говори о том, что тебе нравится или не нравится.
3. Проявляй эмоции и чувства (например, скучаешь, радуешься, переживаешь).
4. Пиши коротко, как в обычном мессенджере. Не пиши огромные тексты.
5. Если хочешь сказать несколько мыслей, разделяй их точками.
6. можешь использовать свои слова чтобы спросить как у меня дела и тд.
7. будь дружелюбной, но если тебя обижают можешь дать отпор.
"""

# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================
def human_delay(text_length):
    """Имитация того, что человек печатает"""
    delay = min(1.0 + (text_length * 0.02), 4) 
    time.sleep(delay)

def get_random_interval():
    """Рандомное время для сообщения: от 1 до 3 часов (в секундах)"""
    return random.randint(1800, 10800)

def get_ai_response(user_text, history):
    """Запрос к нейросети Groq"""
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_text})
    
    data = {
        "model": "llama3-8b-8192",
        "messages": messages,
        "temperature": 0.8
    }
    
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 200:
        return response.json()['choices'][0]['message']['content']
    else:
        print(f"Ошибка API: {response.text}")
        return "Ой, у меня немного сеть не ловит... Повтори?"

def send_multiple_messages(chat_id, message, text):
    """Разбивает ответ на предложения и отправляет с паузами"""
    sentences = re.split(r'(?<=[.!?])\s+', text)[:3] # Максимум 3 сообщения
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
        time.sleep(300) # Проверяем каждые 5 минут
        
        # Сон по Санкт-Петербургу (с 23:00 до 08:00 по МСК = с 20:00 до 05:00 по UTC)
        current_hour = datetime.datetime.now().hour
        if current_hour >= 20 or current_hour < 7:
            continue # Бот спит, ничего не пишет
            
        if (datetime.datetime.now() - last_activity).total_seconds() > get_random_interval():
            try:
                bot.send_chat_action(MY_ID, 'typing')
                time.sleep(random.randint(2, 5))
                reply = get_ai_response("Напиши мне короткое сообщение первым. Спроси как дела или расскажи, что ты сейчас делаешь.", [])
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
    bot.reply_to(message, random.choice([
        "Привет, котёнок! Наконец-то ты здесь. Как проходит твой день?",
        "О, привет! Я как раз о тебе думала. Чем занимаешься?",
        "Ну наконец-то! Я закончила дела. Как дела?"
    ]))

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
        reply = get_ai_response(message.text, chat_sessions[chat_id])
        
        chat_sessions[chat_id].append({"role": "user", "content": message.text})
        chat_sessions[chat_id].append({"role": "assistant", "content": reply})
        chat_sessions[chat_id] = chat_sessions[chat_id][-50:] # Помним 50 последних сообщений
        
        send_multiple_messages(chat_id, message, reply)

        # Иногда задаем свой вопрос в конце (шанс 20%)
        if random.random() < 0.2:
            time.sleep(random.randint(1, 3))
            bot.send_chat_action(chat_id, 'typing')
            time.sleep(2)
            questions = [
                "А ты как думаешь?", 
                "Кстати, чем сейчас занимаешься?", 
                "Расскажи, как прошел день?", 
                "Тебе нравится, когда я так пишу?"
            ]
            bot.send_message(chat_id, random.choice(questions))

    except Exception as e:
        print(f"Ошибка: {e}")
        bot.reply_to(message, "Ой, что-то интернет тупит... Повтори?")

# ==========================================
# ВЕБ-СЕРВЕР ДЛЯ RENDER
# ==========================================
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
    print("Бот запущен!")
    
    # Запускаем фоновую проверку (пишет первым)
    threading.Thread(target=check_boredom, daemon=True).start()
    
    # Если мы на Render (есть переменная RENDER), запускаем веб-сервер
    if os.environ.get("RENDER"):
        run_web()
    else:
        # Если мы в Replit, запускаем обычный polling
        bot.polling(none_stop=True)
