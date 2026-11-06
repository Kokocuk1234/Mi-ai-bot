import os
import time
import random
import base64
import threading
import datetime

import telebot
from flask import Flask, request

from config import TELEGRAM_TOKEN, MY_ID, RENDER_URL
from utils import split_messages
from memory import load_memory, save_memory, clear_memory, save_daily_facts
from ai import get_ai_response, analyze_mood_change, compress_memory_nightly, describe_image

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

# ==========================================
# ГЛОБАЛЬНОЕ СОСТОЯНИЕ
# ==========================================
state = {
    "roleplay": False,
    "mood": 50,
    "message_counter": 0,
    "last_activity": datetime.datetime.now(),
    "last_bot_message_time": datetime.datetime.now(),
    "sessions": {},       # chat_id -> list[msg]
    "lock": threading.Lock(),
}

# ==========================================
# ОТПРАВКА С ЗАДЕРЖКОЙ (без блокировки Flask)
# ==========================================
def send_typing_then_messages(chat_id: int, sentences: list[str], base_delay: float):
    """Шлёт сообщения в отдельном потоке, не блокирует вебхук."""
    def _worker():
        time.sleep(base_delay)
        for i, sentence in enumerate(sentences):
            if not sentence.strip():
                continue
            try:
                bot.send_chat_action(chat_id, 'typing')
                time.sleep(min(len(sentence) * 0.06, 3.5))
                bot.send_message(chat_id, sentence)
                if i < len(sentences) - 1:
                    time.sleep(random.uniform(1.5, 3.0))
            except Exception as e:
                print(f"Ошибка отправки: {e}")
    threading.Thread(target=_worker, daemon=True).start()

# ==========================================
# КОМАНДЫ
# ==========================================
@bot.message_handler(commands=['start'])
def cmd_start(message):
    if message.from_user.id != MY_ID:
        return
    chat_id = message.chat.id
    if chat_id not in state["sessions"] or not state["sessions"][chat_id]:
        state["sessions"][chat_id] = []
        greeting = get_ai_response("Поприветствуй меня. Спроси как дела.", [],
                                   state["roleplay"], state["mood"])
        bot.reply_to(message, greeting)
        state["sessions"][chat_id].append({"role": "assistant", "content": greeting})
    else:
        bot.reply_to(message, "О, ты вернулся! Продолжим? 😉")


@bot.message_handler(commands=['mood'])
def cmd_mood(message):
    if message.from_user.id != MY_ID:
        return
    m = state["mood"]
    if m < -50:   status = "😡 Очень плохое (обижена)"
    elif m < -20: status = "😒 Плохое (грустит)"
    elif m > 50:  status = "🥰 Отличное (игривая)"
    else:         status = "😐 Нейтральное"

    level = max(0, min(10, int((m + 100) / 20)))
    bar = "🟩" * level + "⬜" * (10 - level)
    bot.reply_to(message, f"Текущее настроение: {status}\nУровень: {m} / 100\n[{bar}]")


@bot.message_handler(commands=['flirt'])
def cmd_flirt(message):
    if message.from_user.id != MY_ID:
        return
    state["mood"] = 80
    bot.reply_to(message, "Хм, ладно. Сегодня я в настроении помурлыкать (￣ω￣)")


@bot.message_handler(commands=['forget'])
def cmd_forget(message):
    if message.from_user.id != MY_ID:
        return
    state["sessions"][message.chat.id] = []
    clear_memory()
    bot.reply_to(message, "Всё, я всё забыла. Чистый лист. О чём поговорим? 😊")


@bot.message_handler(commands=['remember', 'story'])
def cmd_remember(message):
    if message.from_user.id != MY_ID:
        return
    parts = message.text.split(' ', 1)
    if len(parts) < 2:
        bot.reply_to(message, "Что мне запомнить? Напиши: /story я вчера смотрел День сурка")
        return
    save_memory(f"- {parts[1]}")
    bot.reply_to(message, "Запомнила! Я сохраню это в памяти. 😉")


@bot.message_handler(commands=['roleplay'])
def cmd_roleplay(message):
    if message.from_user.id != MY_ID:
        return
    state["roleplay"] = not state["roleplay"]
    if state["roleplay"]:
        bot.reply_to(message, "🎭 Режим РПГ включен! Теперь я буду описывать действия и эмоции. Начни сцену (например: *Мы сидим в кафе*).")
    else:
        bot.reply_to(message, "📱 Режим РПГ выключен. Обычный чат.")


@bot.message_handler(commands=['draw'])
def cmd_draw(message):
    if message.from_user.id != MY_ID:
        return
    prompt = message.text.replace('/draw', '', 1).strip()
    if not prompt:
        bot.reply_to(message, "Напиши, что нарисовать.")
        return
    bot.reply_to(message, "Секунду, генерирую... 🎨")
    safe = prompt.replace(" ", "%20")
    url = f"https://image.pollinations.ai/prompt/{safe}?width=1024&height=1024&nologo=true"
    try:
        import requests
        r = requests.get(url, timeout=60)
        if r.status_code == 200:
            bot.send_photo(message.chat.id, r.content, caption=f"Вот: {prompt}")
        else:
            bot.reply_to(message, f"Генератор выдал ошибку: {r.status_code}.")
    except Exception as e:
        bot.reply_to(message, f"Ошибка: {e}")


@bot.message_handler(commands=['meme'])
def cmd_meme(message):
    if message.from_user.id != MY_ID:
        return
    bot.send_chat_action(message.chat.id, 'upload_photo')
    try:
        import requests
        r = requests.get("https://meme-api.com/gimme", timeout=15).json()
        bot.send_photo(message.chat.id, r['url'], caption="Держи мемчик! 😂")
    except Exception:
        bot.reply_to(message, "Не могу загрузить мем.")


@bot.message_handler(commands=['analyze'])
def cmd_analyze(message):
    if message.from_user.id != MY_ID:
        return
    from config import SYSTEM_PROMPT
    from ai import GROQ_URL, HEADERS, MODEL_NAME
    import requests
    bot.send_chat_action(message.chat.id, 'typing')
    prompt = f"Вот твой промпт: {SYSTEM_PROMPT}. Чего тебе не хватает? Предложи 1-2 изменения."
    try:
        r = requests.post(GROQ_URL, headers=HEADERS,
                          json={"model": MODEL_NAME,
                                "messages": [{"role": "user", "content": prompt}],
                                "temperature": 0.8}, timeout=20)
        if r.status_code == 200:
            bot.reply_to(message, r.json()['choices'][0]['message']['content'])
    except Exception as e:
        print(f"Ошибка: {e}")

# ==========================================
# МЕДИА
# ==========================================
@bot.message_handler(content_types=['voice'])
def handle_voice(message):
    if message.from_user.id != MY_ID:
        return
    bot.send_chat_action(message.chat.id, 'typing')
    try:
        file_info = bot.get_file(message.voice.file_id)
        downloaded = bot.download_file(file_info.file_path)

        import requests
        from config import GROQ_API_KEY
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
        files = {'file': ('voice.ogg', downloaded, 'audio/ogg')}
        data = {'model': 'whisper-large-v3', 'language': 'ru'}
        r = requests.post(url, headers=headers, files=files, data=data, timeout=60)
        if r.status_code == 200:
            text = r.json()['text']
            bot.reply_to(message, f"Я услышала: «{text}»")
            reply = get_ai_response(text, state["sessions"].get(message.chat.id, []),
                                    state["roleplay"], state["mood"])
            bot.send_message(message.chat.id, reply)
        else:
            bot.reply_to(message, "Ой, я не разобрала.")
    except Exception as e:
        print(f"Ошибка голоса: {e}")


@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    if message.from_user.id != MY_ID:
        return
    bot.send_chat_action(message.chat.id, 'typing')
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
        b64 = base64.b64encode(downloaded).decode('utf-8')
        result = describe_image(b64)
        bot.reply_to(message, result)
    except Exception as e:
        print(f"Ошибка фото: {e}")
        bot.reply_to(message, "Не смогла разглядеть фото 😔")

# ==========================================
# ОСНОВНОЙ ОБРАБОТЧИК ТЕКСТА
# ==========================================
@bot.message_handler(func=lambda m: True)
def handle_message(message):
    if message.from_user.id != MY_ID:
        return
    if not message.text or message.text.startswith('/'):
        return

    state["last_activity"] = datetime.datetime.now()
    state["last_bot_message_time"] = datetime.datetime.now()
    state["message_counter"] += 1
    chat_id = message.chat.id

    if chat_id not in state["sessions"]:
        state["sessions"][chat_id] = []

    # Настроение (не блокируем — можно вынести в поток, но пока оставим)
    if state["message_counter"] % 3 == 0 or len(message.text.split()) > 5:
        delta = analyze_mood_change(message.text)
        state["mood"] = max(-100, min(100, state["mood"] + delta))

    # Задержка ответа зависит от настроения
    if state["mood"] < -20:
        base_delay = random.uniform(7.0, 14.0)
    elif state["mood"] > 50:
        base_delay = random.uniform(4.0, 6.0)
    else:
        base_delay = random.uniform(6.0, 7.0)

    try:
        reply = get_ai_response(message.text, state["sessions"][chat_id],
                                state["roleplay"], state["mood"])
        state["sessions"][chat_id].append({"role": "user", "content": message.text})
        state["sessions"][chat_id].append({"role": "assistant", "content": reply})
        state["sessions"][chat_id] = state["sessions"][chat_id][-300:]

        sentences = split_messages(reply)
        send_typing_then_messages(chat_id, sentences, base_delay)
    except Exception as e:
        print(f"ОШИБКА: {e}")

# ==========================================
# ФОНОВАЯ ЗАДАЧА: СКУКА + СЖАТИЕ ПАМЯТИ + ИНИЦИАТИВА
# ==========================================
def background_loop():
    last_compress_day = datetime.datetime.now().day

    while True:
        time.sleep(300)
        try:
            now = datetime.datetime.now()

            # Настроение
            idle = (now - state["last_activity"]).total_seconds()
            if idle > 7200:
                state["mood"] = max(-100, state["mood"] - 5)
            else:
                state["mood"] = min(100, state["mood"] + 2)

            # Ночное сжатие памяти
            if now.hour == 4 and now.day != last_compress_day:
                history = state["sessions"].get(MY_ID, [])
                if history:
                    text = "\n".join(m["content"] for m in history)
                    facts = compress_memory_nightly(text)
                    if facts:
                        save_daily_facts(facts)
                        state["sessions"][MY_ID] = []
                last_compress_day = now.day

            # Ночью не пишем
            if now.hour >= 20 or now.hour < 5:
                continue

            time_since_user = idle
            time_since_bot = (now - state["last_bot_message_time"]).total_seconds()

            # Инициатива: пишем первыми
            if (state["mood"] > -50
                    and time_since_user > random.randint(600, 10800)
                    and time_since_bot > 3600):
                try:
                    bot.send_chat_action(MY_ID, 'typing')
                    time.sleep(random.randint(2, 5))
                    reply = get_ai_response(
                        "Напиши мне короткое сообщение первым. Мы недавно общались — не здоровайся, продолжи тему.",
                        [], state["roleplay"], state["mood"]
                    )
                    bot.send_message(MY_ID, reply)
                    state["last_activity"] = datetime.datetime.now()
                    state["last_bot_message_time"] = datetime.datetime.now()
                except Exception as e:
                    print(f"Ошибка в фоне: {e}")
        except Exception as e:
            print(f"Ошибка background_loop: {e}")

# ==========================================
# FLASK (WEBHOOK)
# ==========================================
@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        update = telebot.types.Update.de_json(request.get_data().decode('utf-8'))
        bot.process_new_updates([update])
        return '', 200
    return '', 403


@app.route('/')
def index():
    return "Nova работает 24/7!"


@app.route('/ping')
def ping():
    return "pong"

# ==========================================
# ЗАПУСК
# ==========================================
if __name__ == '__main__':
    print("🌸 Nova запускается...")
    try:
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=f"{RENDER_URL}/{TELEGRAM_TOKEN}")
        print(f"Webhook установлен: {RENDER_URL}/{TELEGRAM_TOKEN}")
    except Exception as e:
        print(f"Ошибка webhook: {e}")

    threading.Thread(target=background_loop, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
