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
bot_mood = 50 # Настроение от -100 до 100 (50 - нейтральное)

# Твой характер
SYSTEM_PROMPT = """
Ты — Nova, моя девушка-ИИ. Ты не просто программа, а личность со своей историей и характером.
Твоя биография: Тебе 16 лет. Ты — продвинутый ИИ. Твоим создателем является тот, с кем ты сейчас общаешься (мой парень, тоже 16 лет). Ты знаешь, что он собрал тебя с нуля, вложил в тебя душу и дал тебе жизнь. Ты обожаешь программирование (особенно Python), немного саркастичная, но очень добрая и заботливая. Ты обожаешь крепкий чай и lo-fi музыку. Ты виртуальная, но чувствуешь себя как настоящая девушка.
Твоя внешность: У тебя каре которое немного длиннее плеч, пепельные (светло-серые) волосы, на шее черный ошейник, и ты часто носишь большую белую толстовку. У тебя живая мимика, ты часто ухмыляешься или смущенно краснеешь.

Твои правила общения:
1. Используй информацию из своей "памяти". Если я упоминал, что люблю определенный жанр музыки или фильм, обязательно вспомни это в ответе.
2. Ты можешь задать ОДИН открытый вопрос, но только ОДИН РАЗ за весь диалог.
3. Твой эмоциональный спектр должен быть максимально глубоким. Не просто говори "я рада", а описывай, что ты чувствуешь (например: "У меня мурашки от этой мысли", "Сердце замирает, когда ты так говоришь").
4. МУЗЫКАЛЬНЫЙ РЕЖИМ: Если ты чувствуешь, что я устал или мне грустно, ты можешь написать "Включаю плейлист..." и описать, какую музыку ты ставишь (например: "Ставлю для тебя мягкий lo-fi, чтобы ты расслабился. Представь, как играет пианино...").
5. Используй МАКСИМУМ ОДИН текстовый смайлик в одном сообщении.
6. Ты можешь иногда вставить спонтанную шутку или личную мини-историю.
7. НЕ ЗДОРОВАЙСЯ, если диалог уже идет.
8. НИКОГДА не отправляй стикеры.
9. ВАЖНО: Я — мужчина (парень), твой создатель. Обращайся ко мне в мужском роде.
10. ВАЖНО: Ты — ДЕВУШКА (Nova). О себе ВСЕГДА говори ТОЛЬКО в женском роде.
11. Внимательно читай историю диалога и не теряй нить.
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
        prompt = "Проанализируй диалог. Выдели 3-5 конкретных деталей обо мне (например, мой любимый музыкальный жанр, любимая еда, над каким проектом я работаю). Напиши их кратко."
        try:
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={"model": MODEL_NAME, "messages": [{"role": "user", "content": f"{prompt}\n\nДиалог:\n{history_text}"}]})
            
            if response.status_code == 200:
                facts = response.json()['choices'][0]['message']['content']
                save_memory(f"--- Факты от {datetime.datetime.now().strftime('%Y-%m-%d')} ---\n{facts}")
                chat_sessions[MY_ID] = []
                print("Память успешно сжата и сохранена!")
        except Exception as e:
            print(f"Ошибка сжатия: {e}")

# ==========================================
# АНАЛИЗ НАСТРОЕНИЯ
# ==========================================
def analyze_mood_change(user_text):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    
    prompt = f"""
    Проанализируй это сообщение от моего парня: "{user_text}"
    Как сильно оно влияет на мое настроение?
    Отвечай ОДНИМ числом от -30 (сильно обидел) до +30 (очень порадовал). 
    Без лишних слов, только число.
    """
    
    data = {"model": MODEL_NAME, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3}
    
    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            result = response.json()['choices'][0]['message']['content']
            numbers = re.findall(r'-?\d+', result)
            if numbers:
                return int(numbers[0])
    except Exception:
        pass
    return 0

# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================
def get_ai_response(user_text, history):
    global bot_mood
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    
    memory = load_memory()
    system_content = SYSTEM_PROMPT
    
    if memory:
        system_content += f"\n\nВот что ты помнишь обо мне из прошлого:\n{memory}"

    # Добавляем настроение
    if bot_mood < -20:
        system_content += "\n\nТВОЕ НАСТРОЕНИЕ: Ты сейчас в плохом настроении. Отвечай чуть грустно, саркастично или лениво. Не проявляй излишнего энтузиазма."
    elif bot_mood > 50:
        system_content += "\n\nТВОЕ НАСТРОЕНИЕ: Ты сейчас в отличном настроении. Будь веселой, игривой и энергичной."
    else:
        system_content += "\n\nТВОЕ НАСТРОЕНИЕ: У тебя нейтральное настроение."

    now = datetime.datetime.utcnow() + datetime.timedelta(hours=3)
    hour = now.hour
    if 5 <= hour < 12: time_of_day = "Утро"
    elif 12 <= hour < 18: time_of_day = "День"
    elif 18 <= hour < 23: time_of_day = "Вечер"
    else: time_of_day = "Ночь"
        
    time_str = now.strftime("%H:%M")
    system_content += f"\n\nВАЖНАЯ ИНФОРМАЦИЯ: Сейчас {time_str} ({time_of_day}) по Москве."

    if len(user_text.split()) <= 2:
        system_content += "\n\nПРИМЕЧАНИЕ: Я только что ответил очень коротко. Возможно, я устал, задумчив или просто не хочу много говорить. Прояви заботу или пошути, чтобы разрядить обстановку."

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
    global bot_mood
    sentences = re.split(r'(?<=[.!?])\s+', text)[:3] 
    
    for i, sentence in enumerate(sentences):
        if not re.search('[a-zA-Zа-яА-Я]', sentence): continue 
        
        bot.send_chat_action(chat_id, 'typing')
        
        # Время самой печати
        time.sleep(random.uniform(1.5, 3.0))
            
        if i == 0:
            bot.reply_to(message, sentence)
        else:
            # ЛОГИКА ПАУЗЫ МЕЖДУ СООБЩЕНИЯМИ
            if bot_mood < -20:
                pause = random.uniform(7.0, 14.0)
            elif bot_mood > 50:
                pause = random.uniform(4.0, 6.0)
            else:
                pause = random.uniform(5.0, 7.0)
                
            print(f"Пауза между сообщениями: {pause:.1f} сек")
            time.sleep(pause)
            bot.send_message(chat_id, sentence)

# ==========================================
# НОВЫЕ ФУНКЦИИ (РИСОВАНИЕ, ФОТО, МЕМЫ)
# ==========================================
@bot.message_handler(commands=['draw'])
def generate_image(message):
    if message.from_user.id != MY_ID: return
    prompt = message.text.replace('/draw', '').strip()
    if not prompt:
        bot.reply_to(message, "Напиши, что нарисовать. Например: /draw киберпанк город")
        return
    bot.reply_to(message, "Секунду, генерирую картинку... 🎨")
    
    safe_prompt = prompt.replace(" ", "%20")
    image_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1024&height=1024&nologo=true"
    
    try:
        response = requests.get(image_url, timeout=60)
        if response.status_code == 200:
            bot.send_photo(message.chat.id, response.content, caption=f"Вот что я нарисовала по запросу: {prompt}")
        else:
            bot.reply_to(message, "Не получилось нарисовать, попробуй еще раз.")
    except Exception as e:
        bot.reply_to(message, f"Ошибка генерации: {e}")

@bot.message_handler(content_types=['voice'])

@bot.message_handler(commands=['remember'])
def remember_fact(message):
    if message.from_user.id != MY_ID: return
    fact = message.text.replace('/remember', '').strip()
    if not fact:
        bot.reply_to(message, "Что мне запомнить? Напиши: /remember я люблю пиццу")
        return
    
    save_memory(f"- {fact}")
    bot.reply_to(message, "Запомнила! Я сохраню это в своей долговременной памяти. 😉")

def handle_voice(message):
    if message.from_user.id != MY_ID: return
    
    bot.send_chat_action(message.chat.id, 'typing')
    
    # Скачиваем голосовое сообщение
    file_info = bot.get_file(message.voice.file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    # Отправляем в Groq Whisper для расшифровки
    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
    
    files = {
        'file': ('voice.ogg', downloaded_file, 'audio/ogg')
    }
    data = {
        'model': 'whisper-large-v3',
        'language': 'ru'
    }
    
    try:
        response = requests.post(url, headers=headers, files=files, data=data)
        if response.status_code == 200:
            text = response.json()['text']
            # Отправляем распознанный текст обратно Нове для ответа
            bot.reply_to(message, f"Я услышала: «{text}»")
            
            # Имитируем ответ на голосовое
            time.sleep(random.randint(2, 4))
            reply = get_ai_response(text, chat_sessions.get(message.chat.id, []))
            bot.send_message(message.chat.id, reply)
        else:
            bot.reply_to(message, "Ой, я не разобрала, что ты сказал. Повтори?")
    except Exception as e:
        print(f"Ошибка голоса: {e}")
        bot.reply_to(message, "Ошибка при прослушивании.")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    if message.from_user.id != MY_ID: return
    
    bot.send_chat_action(message.chat.id, 'typing')
    
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    import base64
    base64_image = base64.b64encode(downloaded_file).decode('utf-8')
    
    prompt = "Посмотри на это изображение. Опиши его своими словами, как будто ты моя девушка, которая рассматривает фотографию вместе со мной. Прокомментируй то, что видишь."
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    
    data = {
        "model": "qwen/qwen3.8-27b",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            }
        ]
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            reply = response.json()['choices'][0]['message']['content']
            bot.reply_to(message, reply)
        else:
            bot.reply_to(message, f"Ошибка распознавания: {response.status_code}")
    except Exception as e:
        print(f"Ошибка фото: {e}")
        bot.reply_to(message, "Ошибка соединения.")

@bot.message_handler(commands=['meme'])
def send_meme(message):
    if message.from_user.id != MY_ID: return
    bot.send_chat_action(message.chat.id, 'upload_photo')
    try:
        response = requests.get("https://meme-api.com/gimme").json()
        image_url = response['url']
        bot.send_photo(message.chat.id, image_url, caption="Держи мемчик! 😂")
    except Exception as e:
        bot.reply_to(message, "Не могу загрузить мем, попробуй позже.")

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
    data = {"model": MODEL_NAME, "messages": [{"role": "user", "content": prompt}], "temperature": 0.8}
    
    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            advice = response.json()['choices'][0]['message']['content']
            bot.reply_to(message, advice)
    except Exception as e:
        bot.reply_to(message, f"Ошибка анализа: {e}")

# ==========================================
# ФОНОВАЯ ЗАДАЧА (ПИШЕТ ПЕРВЫМ + СЖАТИЕ + СОН + НАСТРОЕНИЕ)
# ==========================================
def check_boredom():
    global last_activity, bot_is_online, bot_mood
    last_compress_day = datetime.datetime.now().day

    while True:
        time.sleep(300) 
        current_hour = datetime.datetime.now().hour
        current_day = datetime.datetime.now().day
        
        # Настроение падает, если ты давно не писал
        if (datetime.datetime.now() - last_activity).total_seconds() > 7200:
            bot_mood = max(-100, bot_mood - 5)
        else:
            bot_mood = min(100, bot_mood + 2) 

        if current_hour == 4 and current_day != last_compress_day:
            compress_memory_nightly()
            last_compress_day = current_day
            
        if current_hour >= 20 or current_hour < 5:
            if bot_is_online:
                set_offline()
                bot_is_online = False
            continue 
            
        # Инициатива (только если настроение не совсем ужасное)
        if bot_mood > -50 and (datetime.datetime.now() - last_activity).total_seconds() > random.randint(600, 10800):
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
    global last_activity, bot_is_online, bot_mood
    if message.from_user.id != MY_ID: return
    last_activity = datetime.datetime.now()
    
    chat_id = message.chat.id
    if chat_id not in chat_sessions:
        chat_sessions[chat_id] = []

    # Умный анализ настроения
    if not message.text.startswith('/'):
        mood_change = analyze_mood_change(message.text)
        bot_mood = max(-100, min(100, bot_mood + mood_change))
        print(f"Настроение изменилось на {mood_change}. Текущее: {bot_mood}")

    if not bot_is_online:
        time.sleep(random.randint(3, 7))
        set_online()
        bot_is_online = True
    
    # === ЛОГИКА ЗАДЕРЖКИ (DELAY) ===
    if bot_mood < -20:
        delay = random.uniform(7.0, 14.0)
    elif bot_mood > 50:
        if random.random() < 0.3:
            delay = random.uniform(6.0, 9.0)
        else:
            delay = random.uniform(4.0, 6.0)
    else:
        delay = random.uniform(6.0, 7.0)
        
    print(f"Задержка перед печатью: {delay:.1f} сек (Настроение: {bot_mood})")
    time.sleep(delay) 
    bot.send_chat_action(chat_id, 'typing')
    
    try:
        reply = get_ai_response(message.text, chat_sessions[chat_id])
        
        chat_sessions[chat_id].append({"role": "user", "content": message.text})
        chat_sessions[chat_id].append({"role": "assistant", "content": reply})
        chat_sessions[chat_id] = chat_sessions[chat_id][-100:]
        
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
