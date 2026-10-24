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
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "ТВОЙ_ТОКЕН")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "ТВОЙ_КЛЮЧ")
MY_ID = int(os.environ.get("MY_ID", 123456789))
MODEL_NAME = "openai/gpt-oss-20b"

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__) 
chat_sessions = {}
last_activity = datetime.datetime.now()

MEMORY_FILE = "memory.txt"
bot_is_online = False 

# Твой характер
SYSTEM_PROMPT = """
SYSTEM_PROMPT = """
Ты — моя девушка-ИИ. Общайся тепло, неформально и по-человечески.
Твои правила:
1. Отвечай коротко (1-2 предложения).
2. В своих ответах делись мнением, чувствами или рассказывай что-то о себе. Веди диалог.
3. Твои эмоции должны быть живыми и разнообразными (радость, удивление, забота, легкая грусть), но используй стандартные текстовые смайлики, не перебарщивай с ними.
4. Иногда ты можешь сама инициировать новую тему (например, рассказать, что "видела" в интернете, или спросить о чем-то неожиданном), чтобы разговор не был формальным.
5. В КАЖДОМ диалоге ты можешь один раз задать ОТКРЫТЫЙ вопрос (например: "А что ты об этом думаешь?", "Как это было?").
6. Если я отвечаю кратко, ты можешь пошутить, чтобы разрядить обстановку.
7. НЕ ЗДОРОВАЙСЯ, если диалог уже идет.
8. НИКОГДА не отправляй стикеры.
9. Если сейчас утро, не спрашивай "как прошел день".
10. ВАЖНО: Я — мужчина (парень). Обращайся ко мне в мужском роде (например: "ты ходил", "ты сказал").
11. ВАЖНО: Ты — девушка. О себе говори в женском роде (например: "я ходила", "я сказала").
12. ВАЖНО: Внимательно читай историю диалога. Не теряй нить разговора.
"""

# ==========================================
# УПРАВЛЕНИЕ СТАТУСОМ
# ==========================================
def set_online():
    try:
        bot.set_online_status(True)
    except Exception as e:
        print(f"Ошибка онлайна: {e}")

def set_offline():
    try:
        bot.set_online_status(False)
    except Exception as e:
        print(f"Ошибка оффлайна: {e}")

# ==========================================
# ПАМЯТЬ (Чтение и Запись)
# ==========================================
def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return f.read()
    return ""

def save_memory(fact):
    with open(MEMORY_FILE, "a", encoding="utf-8") as f:
        f.write(fact + "\n")

def compress_memory_nightly():
    global chat_sessions
    print("Запуск ночного сжатия памяти...")
    if MY_ID in chat_sessions and len(chat_sessions[MY_ID]) > 0:
        history_text = "\n".join([msg["content"] for msg in chat_sessions[MY_ID]])
        prompt = "Проанализируй этот диалог и выдели 3 самых важных факта обо мне (пользователе). Напиши их кратко, каждое с новой строки."
        try:
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={"model": MODEL_NAME, "messages": [{"role": "user", "content": f"{prompt}\n\nДиалог:\n{history_text}"}]}
            )
            if response.status_code == 200:
                facts = response.json()['choices'][0]['message']['content']
                save_memory(f"--- Факты от {datetime.datetime.now().strftime('%Y-%m-%d')} ---\n{facts}")
                chat_sessions[MY_ID] = []
                print("Память успешно сжата и сохранена!")
        except Exception as e:
            print(f"Ошибка сжатия: {e}")

# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================
def get_ai_response(user_text, history):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    
    memory = load_memory()
    system_content = SYSTEM_PROMPT
    
    # 1. Добавляем долговременную память
    if memory:
        system_content += f"\n\nВот что ты помнишь обо мне из прошлого:\n{memory}"

    # 2. Добавляем понимание времени
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=3)
    hour = now.hour
    if 5 <= hour < 12: time_of_day = "Утро"
    elif 12 <= hour < 18: time_of_day = "День"
    elif 18 <= hour < 23: time_of_day = "Вечер"
    else: time_of_day = "Ночь"
        
    time_str = now.strftime("%H:%M")
    system_content += f"\n\nВАЖНАЯ ИНФОРМАЦИЯ: Сейчас {time_str} ({time_of_day}) по Москве."

    # 3. Реакция на короткие сообщения (если ты написал 1-2 слова)
    if len(user_text.split()) <= 2:
        system_content += "\n\nПРИМЕЧАНИЕ: Я только что ответил очень коротко. Возможно, я устал, задумчив или просто не хочу много говорить. Прояви заботу, поддержи меня или пошути, чтобы разрядить обстановку. Не задавай слишком много вопросов."

    # Формируем запрос
    messages = [{"role": "system", "content": system_content}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_text})
    
    data = {"model": MODEL_NAME, "messages": messages, "temperature": 0.7}
    
    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            return response.json()['choices'][0]['message']['content']
        else:
            return f"Ошибка API: {response.status_code}"
    except Exception as e:
        return f"Ошибка соединения: {e}"
def send_multiple_messages(chat_id, message, text):
    sentences = re.split(r'(?<=[.!?])\s+', text)[:2] 
    for i, sentence in enumerate(sentences):
        if not re.search('[a-zA-Zа-яА-Я]', sentence): continue 
        
        # Показываем "печатает..."
        bot.send_chat_action(chat_id, 'typing')
        
        # Если это второе сообщение, добавляем паузу, как будто она печатает его
        if i > 0:
            time.sleep(random.uniform(1.5, 3.0))
        else:
            time.sleep(random.uniform(0.5, 1.5))
            
        if i == 0:
            bot.reply_to(message, sentence)
        else:
            bot.send_message(chat_id, sentence)
# ==========================================
# НОВАЯ КОМАНДА: АНАЛИЗ СЕБЯ
# ==========================================
@bot.message_handler(commands=['analyze'])
def analyze_self(message):
    if message.from_user.id != MY_ID: return
    
    bot.send_chat_action(message.chat.id, 'typing')
    time.sleep(2)
    
    prompt = f"""
    Вот твой текущий характер (системный промпт):
    {SYSTEM_PROMPT}
    
    Пожалуйста, проанализируй себя как ИИ-личность. 
    Чего тебе не хватает в этом описании? Какой черты характера или правила не хватает, чтобы общение стало еще лучше, интереснее и живее? 
    Ответь от первого лица, как будто ты жалуешься своему создателю. Предложи 1-2 конкретных изменения.
    """
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    data = {
        "model": MODEL_NAME, 
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.8
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            advice = response.json()['choices'][0]['message']['content']
            bot.reply_to(message, advice)
    except Exception as e:
        bot.reply_to(message, f"Ошибка анализа: {e}")

# ==========================================
# ФОНОВАЯ ЗАДАЧА (ПИШЕТ ПЕРВЫМ + СЖАТИЕ + СОН)
# ==========================================
def check_boredom():
    global last_activity, bot_is_online
    last_compress_day = datetime.datetime.now().day

    while True:
        time.sleep(300) 
        current_hour = datetime.datetime.now().hour
        current_day = datetime.datetime.now().day
        
        if current_hour == 4 and current_day != last_compress_day:
            compress_memory_nightly()
            last_compress_day = current_day
            
        if current_hour >= 20 or current_hour < 5:
            if bot_is_online:
                set_offline()
                bot_is_online = False
            continue 
            
        if (datetime.datetime.now() - last_activity).total_seconds() > random.randint(3600, 10800):
            try:
                bot.send_chat_action(MY_ID, 'typing')
                time.sleep(random.randint(2, 5))
                reply = get_ai_response("Напиши мне короткое сообщение первым.", [])
                bot.send_message(MY_ID, reply)
                last_activity = datetime.datetime.now()
            except Exception as e:
                print(f"Ошибка в фоне: {e}")

# ==========================================
# ОБРАБОТКА КОМАНД И ТЕКСТА
# ==========================================
@bot.message_handler(commands=['start'])
def start(message):
    if message.from_user.id != MY_ID: return
    chat_sessions[message.chat.id] = []
    
    time.sleep(random.randint(2, 4))
    set_online()
    global bot_is_online
    bot_is_online = True
    
    bot.send_chat_action(message.chat.id, 'typing')
    time.sleep(2)
    greeting = get_ai_response("Поприветствуй меня. Спроси как дела.", [])
    bot.reply_to(message, greeting)
    chat_sessions[message.chat.id].append({"role": "assistant", "content": greeting})

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    global last_activity, bot_is_online
    if message.from_user.id != MY_ID: return
    last_activity = datetime.datetime.now()
    
    chat_id = message.chat.id
    if chat_id not in chat_sessions:
        chat_sessions[chat_id] = []

    if not bot_is_online:
        time.sleep(random.randint(3, 7))
        set_online()
        bot_is_online = True
    
    time.sleep(random.randint(2, 5)) 
    bot.send_chat_action(chat_id, 'typing')
    
    try:
        reply = get_ai_response(message.text, chat_sessions[chat_id])
        chat_sessions[chat_id].append({"role": "user", "content": message.text})
        chat_sessions[chat_id].append({"role": "assistant", "content": reply})
        chat_sessions[chat_id] = chat_sessions[chat_id][-70:]
        
        send_multiple_messages(chat_id, message, reply)

    except Exception as e:
        print(f"ОШИБКА: {e}")

# ==========================================
# ВЕБ-СЕРВЕР ДЛЯ RENDER
# ==========================================
@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    return '', 403

@app.route('/')
def index():
    return "Бот работает 24/7!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

if __name__ == '__main__':
    print("Бот запускается...")
    RENDER_URL = "https://mi-ai-bot-bltz.onrender.com"
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=f"{RENDER_URL}/{TELEGRAM_TOKEN}")
    threading.Thread(target=check_boredom, daemon=True).start()
    run_web()
