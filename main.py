import os
import time
import random
import base64
import threading
import datetime
from collections import deque
from urllib.parse import quote

import requests
import telebot
from telebot.types import ReactionTypeEmoji
from flask import Flask, request

from config import (
    TELEGRAM_TOKEN, MY_ID, RENDER_URL, WEBHOOK_SECRET, SYSTEM_PROMPT,
    DEBOUNCE_SECONDS, HISTORY_STORED, HISTORY_TAIL_AFTER_NIGHT,
    FACTS_EVERY_N_MESSAGES, QUIET_FROM_HOUR, QUIET_TO_HOUR,
    MAX_UNANSWERED_INITIATIVES, STICKER_IDS,
)
from utils import now_msk, split_messages, typing_delay, is_school_time
from memory import (
    load_memory, save_memory, clear_memory, save_daily_facts,
    load_history, save_history,
)
from ai import (
    get_ai_response, analyze_mood_change, compress_memory_nightly,
    extract_facts, describe_image, transcribe_audio, quick_ask,
)

bot = telebot.TeleBot(TELEGRAM_TOKEN or "0:placeholder", threaded=False)
app = Flask(__name__)

# ==========================================
# ГЛОБАЛЬНОЕ СОСТОЯНИЕ (один пользователь)
# ==========================================
lock = threading.RLock()          # защищает state
reply_lock = threading.Lock()     # один ответ за раз

state = {
    "roleplay": False,
    "mood": 50,
    "message_counter": 0,
    "last_activity": now_msk(),
    "last_bot_message_time": now_msk(),
    "history": load_history(),    # [{"role":..., "content":...}]
    "pending": [],                # накопленные сообщения для дебаунса
    "pending_msg_id": None,
    "timer": None,
    "unanswered_initiatives": 0,
    "initiative_after": random.randint(3600, 10800),
}
seen_ids = deque(maxlen=300)      # защита от повторной доставки вебхука

PHRASES_FAIL = ["сек, у меня что-то глючит", "ой, интернет завис, напиши ещё раз чуть позже", "эм, я зависла. повтори?"]
ACK_SHORT = {"ок", "окей", "ясно", "понятно", "ладно", "хорошо", "ага", "угу", "бывает"}


def owner_only(func):
    def wrapper(message):
        if message.from_user.id != MY_ID:
            return
        return func(message)
    wrapper.__name__ = func.__name__
    return wrapper


def add_history(role: str, content: str):
    with lock:
        state["history"].append({"role": role, "content": content})
        state["history"] = state["history"][-HISTORY_STORED:]
        snapshot = list(state["history"])
    save_history(snapshot)


def touch_activity():
    with lock:
        state["last_activity"] = now_msk()
        state["unanswered_initiatives"] = 0
        state["initiative_after"] = random.randint(3600, 10800)


# ==========================================
# ПОВЕДЕНИЕ: реакции, задержки, отправка
# ==========================================
def maybe_react(chat_id: int, msg_id: int, force: bool = False) -> bool:
    mood = state["mood"]
    if not force and random.random() > 0.15:
        return False
    if mood > 50:
        pool = ["❤", "🥰", "🔥", "😍"]
    elif mood < -20:
        pool = ["🤨", "😐"]
    else:
        pool = ["😁", "👀", "🤣", "❤"]
    try:
        bot.set_message_reaction(chat_id, msg_id, [ReactionTypeEmoji(random.choice(pool))])
        return True
    except Exception as e:
        print(f"Реакция не поставилась: {e}")
        return False


def compute_delay() -> float:
    mood = state["mood"]
    if mood < -20:
        delay = random.uniform(6.0, 12.0)
    elif mood > 50:
        delay = random.uniform(2.0, 4.5)
    else:
        delay = random.uniform(3.0, 6.0)
    if is_school_time() and random.random() < 0.5:
        delay += random.uniform(8.0, 30.0)   # на уроке отвечает не сразу
    return delay


def send_parts(chat_id: int, parts: list[str]):
    for i, part in enumerate(parts):
        if not part.strip():
            continue
        try:
            bot.send_chat_action(chat_id, "typing")
            time.sleep(typing_delay(part))
            bot.send_message(chat_id, part)
            with lock:
                state["last_bot_message_time"] = now_msk()
            if i < len(parts) - 1:
                time.sleep(random.uniform(0.8, 2.0))
        except Exception as e:
            print(f"Ошибка отправки: {e}")

    if STICKER_IDS and state["mood"] > 30 and random.random() < 0.08:
        try:
            time.sleep(random.uniform(1.0, 2.0))
            bot.send_sticker(chat_id, random.choice(STICKER_IDS))
        except Exception as e:
            print(f"Ошибка стикера: {e}")


# ==========================================
# ДЕБАУНС: несколько сообщений подряд → один ответ
# ==========================================
def enqueue(text: str, message):
    """Копит сообщения и запускает ответ через DEBOUNCE_SECONDS тишины."""
    if message.message_id in seen_ids:
        return
    seen_ids.append(message.message_id)

    touch_activity()
    with lock:
        state["pending"].append(text)
        state["pending_msg_id"] = message.message_id
        if state["timer"]:
            state["timer"].cancel()
        t = threading.Timer(DEBOUNCE_SECONDS, flush_pending, args=(message.chat.id,))
        t.daemon = True
        state["timer"] = t
        t.start()


def flush_pending(chat_id: int):
    with lock:
        texts = state["pending"]
        msg_id = state["pending_msg_id"]
        state["pending"] = []
        state["timer"] = None
    if not texts:
        return
    with reply_lock:
        try:
            process_user_input(chat_id, texts, msg_id)
        except Exception as e:
            print(f"ОШИБКА process_user_input: {e}")


def update_mood(user_text: str):
    with lock:
        state["message_counter"] += 1
        counter = state["message_counter"]
    if counter % 3 == 0 or len(user_text.split()) > 5:
        delta = analyze_mood_change(user_text)
        with lock:
            state["mood"] = max(-100, min(100, state["mood"] + delta))


def process_user_input(chat_id: int, texts: list[str], msg_id: int):
    user_text = "\n".join(texts)
    started = time.time()

    update_mood(user_text)

    # Иногда на короткое «ок» достаточно реакции без текста
    if (len(texts) == 1 and user_text.strip().lower() in ACK_SHORT
            and not state["roleplay"] and random.random() < 0.4):
        if maybe_react(chat_id, msg_id, force=True):
            add_history("user", user_text)
            return

    maybe_react(chat_id, msg_id)

    with lock:
        history = list(state["history"])
        roleplay = state["roleplay"]
        mood = state["mood"]

    reply = get_ai_response(user_text, history, roleplay, mood)

    if not reply:
        # Ошибку в историю не пишем, отвечаем в образе
        bot.send_message(chat_id, random.choice(PHRASES_FAIL))
        return

    # Задержка считается с момента получения, а не после генерации
    remaining = compute_delay() - (time.time() - started)
    if remaining > 0:
        time.sleep(remaining)

    add_history("user", user_text)
    add_history("assistant", reply)

    send_parts(chat_id, split_messages(reply, roleplay=roleplay))

    # Каждые N сообщений вытаскиваем факты в долгую память
    with lock:
        counter = state["message_counter"]
    if counter % FACTS_EVERY_N_MESSAGES == 0:
        threading.Thread(target=extract_and_save_facts, daemon=True).start()


def extract_and_save_facts():
    with lock:
        recent = state["history"][-FACTS_EVERY_N_MESSAGES * 2:]
    if not recent:
        return
    text = "\n".join(
        ("Я: " if m["role"] == "user" else "Nova: ") + m["content"] for m in recent
    )
    facts = extract_facts(text)
    if facts.strip():
        save_daily_facts(facts)


# ==========================================
# КОМАНДЫ
# ==========================================
@bot.message_handler(commands=["start"])
@owner_only
def cmd_start(message):
    chat_id = message.chat.id
    with lock:
        has_history = bool(state["history"])
    if not has_history:
        greeting = get_ai_response("Поприветствуй меня. Спроси как дела.", [],
                                   state["roleplay"], state["mood"])
        if greeting:
            bot.reply_to(message, greeting)
            add_history("assistant", greeting)
        else:
            bot.reply_to(message, "привет! (у меня что-то глючит, но я тут)")
    else:
        bot.reply_to(message, "О, ты вернулся! Продолжим? 😉")


@bot.message_handler(commands=["mood"])
@owner_only
def cmd_mood(message):
    m = state["mood"]
    if m < -50:   status = "😡 Очень плохое (обижена)"
    elif m < -20: status = "😒 Плохое (грустит)"
    elif m > 50:  status = "🥰 Отличное (игривая)"
    else:         status = "😐 Нейтральное"
    level = max(0, min(10, int((m + 100) / 20)))
    bar = "🟩" * level + "⬜" * (10 - level)
    bot.reply_to(message, f"Текущее настроение: {status}\nУровень: {m} / 100\n[{bar}]")


@bot.message_handler(commands=["flirt"])
@owner_only
def cmd_flirt(message):
    state["mood"] = 80
    bot.reply_to(message, "Хм, ладно. Сегодня я в настроении помурлыкать (￣ω￣)")


@bot.message_handler(commands=["forget"])
@owner_only
def cmd_forget(message):
    with lock:
        state["history"] = []
        state["pending"] = []
    save_history([])
    clear_memory()
    bot.reply_to(message, "Всё, я всё забыла. Чистый лист. О чём поговорим? 😊")


@bot.message_handler(commands=["remember", "story"])
@owner_only
def cmd_remember(message):
    parts = message.text.split(" ", 1)
    if len(parts) < 2 or not parts[1].strip():
        bot.reply_to(message, "Что мне запомнить? Напиши: /story я вчера смотрел День сурка")
        return
    save_memory(f"- {parts[1].strip()}")
    bot.reply_to(message, "Запомнила! Я сохраню это в памяти. 😉")


@bot.message_handler(commands=["roleplay"])
@owner_only
def cmd_roleplay(message):
    with lock:
        state["roleplay"] = not state["roleplay"]
        on = state["roleplay"]
    if on:
        bot.reply_to(message, "🎭 Режим РПГ включен! Теперь я буду описывать действия и эмоции. Начни сцену (например: *Мы сидим в кафе*).")
    else:
        bot.reply_to(message, "📱 Режим РПГ выключен. Обычный чат.")


@bot.message_handler(commands=["draw"])
@owner_only
def cmd_draw(message):
    prompt = message.text.replace("/draw", "", 1).strip()
    if not prompt:
        bot.reply_to(message, "Напиши, что нарисовать.")
        return
    bot.reply_to(message, "Секунду, генерирую... 🎨")

    def worker():
        url = f"https://image.pollinations.ai/prompt/{quote(prompt)}?width=1024&height=1024&nologo=true"
        try:
            r = requests.get(url, timeout=60)
            if r.status_code == 200:
                bot.send_photo(message.chat.id, r.content, caption=f"Вот: {prompt}")
            else:
                bot.reply_to(message, f"Генератор выдал ошибку: {r.status_code}.")
        except Exception as e:
            bot.reply_to(message, f"Ошибка: {e}")
    threading.Thread(target=worker, daemon=True).start()


@bot.message_handler(commands=["meme"])
@owner_only
def cmd_meme(message):
    def worker():
        try:
            bot.send_chat_action(message.chat.id, "upload_photo")
            r = requests.get("https://meme-api.com/gimme", timeout=15).json()
            bot.send_photo(message.chat.id, r["url"], caption="Держи мемчик! 😂")
        except Exception:
            bot.reply_to(message, "Не могу загрузить мем.")
    threading.Thread(target=worker, daemon=True).start()


@bot.message_handler(commands=["analyze"])
@owner_only
def cmd_analyze(message):
    def worker():
        bot.send_chat_action(message.chat.id, "typing")
        out = quick_ask(f"Вот твой промпт: {SYSTEM_PROMPT}. Чего тебе не хватает? Предложи 1-2 изменения.")
        bot.reply_to(message, out or "Не получилось, API молчит.")
    threading.Thread(target=worker, daemon=True).start()


# ==========================================
# МЕДИА (обрабатываем в потоке, чтобы вебхук отвечал сразу)
# ==========================================
@bot.message_handler(content_types=["voice"])
@owner_only
def handle_voice(message):
    def worker():
        try:
            bot.send_chat_action(message.chat.id, "typing")
            file_info = bot.get_file(message.voice.file_id)
            audio = bot.download_file(file_info.file_path)
            text = transcribe_audio(audio)
            if text:
                enqueue(f"(голосовое сообщение) {text}", message)
            else:
                bot.reply_to(message, "Ой, я не разобрала. Скажи ещё раз?")
        except Exception as e:
            print(f"Ошибка голоса: {e}")
    threading.Thread(target=worker, daemon=True).start()


@bot.message_handler(content_types=["photo"])
@owner_only
def handle_photo(message):
    def worker():
        try:
            bot.send_chat_action(message.chat.id, "typing")
            file_info = bot.get_file(message.photo[-1].file_id)
            downloaded = bot.download_file(file_info.file_path)
            desc = describe_image(base64.b64encode(downloaded).decode("utf-8"))
            if not desc:
                bot.reply_to(message, "Не смогла разглядеть фото 😔")
                return
            caption = f" Подпись: {message.caption}" if message.caption else ""
            enqueue(f"[Я прислал тебе фото. Что на нём: {desc}.{caption}] "
                    f"Отреагируй как Nova, не пересказывай описание сухо.", message)
        except Exception as e:
            print(f"Ошибка фото: {e}")
            bot.reply_to(message, "Не смогла разглядеть фото 😔")
    threading.Thread(target=worker, daemon=True).start()


# ==========================================
# ТЕКСТ
# ==========================================
@bot.message_handler(func=lambda m: True)
@owner_only
def handle_message(message):
    if not message.text or message.text.startswith("/"):
        return
    enqueue(message.text, message)


# ==========================================
# ФОН: настроение, сжатие памяти, инициатива
# ==========================================
def background_loop():
    last_compress_date = now_msk().date()

    while True:
        time.sleep(300)
        try:
            now = now_msk()
            with lock:
                idle = (now - state["last_activity"]).total_seconds()
                since_bot = (now - state["last_bot_message_time"]).total_seconds()

                # Настроение: скука при долгом молчании, иначе дрейф к 50
                if idle > 7200:
                    state["mood"] = max(-40, state["mood"] - 3)
                else:
                    m = state["mood"]
                    state["mood"] = m + min(3, 50 - m) if m < 50 else m - min(3, m - 50)

            # Ночное сжатие памяти (в 4 утра по Москве)
            if now.hour == 4 and now.date() != last_compress_date:
                with lock:
                    history = list(state["history"])
                if history:
                    text = "\n".join(
                        ("Я: " if m["role"] == "user" else "Nova: ") + m["content"]
                        for m in history
                    )
                    facts = compress_memory_nightly(text)
                    if facts:
                        save_daily_facts(facts)
                        # Хвост оставляем, чтобы контекст не обнулялся
                        with lock:
                            state["history"] = state["history"][-HISTORY_TAIL_AFTER_NIGHT:]
                            snapshot = list(state["history"])
                        save_history(snapshot)
                last_compress_date = now.date()

            # Тихие часы
            if now.hour >= QUIET_FROM_HOUR or now.hour < QUIET_TO_HOUR:
                continue

            with lock:
                can_write = (
                    state["mood"] > -50
                    and idle > state["initiative_after"]
                    and since_bot > 3600
                    and state["unanswered_initiatives"] < MAX_UNANSWERED_INITIATIVES
                    and not state["pending"]
                )
                history = list(state["history"])
                roleplay = state["roleplay"]
                mood = state["mood"]

            if not can_write or not MY_ID:
                continue

            with reply_lock:
                bot.send_chat_action(MY_ID, "typing")
                time.sleep(random.randint(2, 5))
                reply = get_ai_response(
                    "[Напиши мне короткое сообщение первой. Если в последних сообщениях была тема — "
                    "продолжи её без приветствия. Если разговор давно закончился — расскажи что-нибудь "
                    "про свой день или поделись мыслью.]",
                    history[-10:], roleplay, mood,
                )
                if not reply:
                    continue
                add_history("assistant", reply)
                send_parts(MY_ID, split_messages(reply, roleplay=roleplay))

            with lock:
                state["last_activity"] = now_msk()
                state["last_bot_message_time"] = now_msk()
                state["unanswered_initiatives"] += 1
                state["initiative_after"] = random.randint(7200, 14400)
        except Exception as e:
            print(f"Ошибка background_loop: {e}")


# ==========================================
# FLASK (WEBHOOK)
# ==========================================
@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    if WEBHOOK_SECRET and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        return "", 403
    if request.headers.get("content-type") == "application/json":
        update = telebot.types.Update.de_json(request.get_data().decode("utf-8"))
        bot.process_new_updates([update])
        return "", 200
    return "", 403


@app.route("/")
def index():
    return "Nova работает 24/7!"


@app.route("/ping")
def ping():
    return "pong"


# ==========================================
# ЗАПУСК (работает и с python main.py, и с gunicorn)
# ==========================================
_started = False


def startup():
    global _started
    if _started or not TELEGRAM_TOKEN:
        return
    _started = True
    print("🌸 Nova запускается...")
    try:
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=f"{RENDER_URL}/{TELEGRAM_TOKEN}",
                        secret_token=WEBHOOK_SECRET or None)
        print(f"Webhook установлен: {RENDER_URL}/<token>")
    except Exception as e:
        print(f"Ошибка webhook: {e}")
    threading.Thread(target=background_loop, daemon=True).start()


startup()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
