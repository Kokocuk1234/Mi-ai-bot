import re
import time
from typing import Optional

import requests

from config import (
    GROQ_API_KEY, MODEL_NAME, FALLBACK_MODEL, FAST_MODEL, VISION_MODEL, WHISPER_MODEL,
    SYSTEM_PROMPT, STYLE_PROMPT, ROLEPLAY_PROMPT, CHAT_MODE_PROMPT,
    HISTORY_IN_PROMPT,
)
from utils import (
    now_msk, time_of_day, weekday_name, check_holiday,
    is_school_time, daily_life_state,
)
from memory import load_memory

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_AUDIO_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
HEADERS = {
    "Authorization": f"Bearer {GROQ_API_KEY}",
    "Content-Type": "application/json",
}

ACK_PHRASES = {"ну всякое бывает", "бывает", "ясно", "понятно", "ок", "окей", "хорошо", "ладно"}


# ==========================================
# НИЗКИЙ УРОВЕНЬ: запрос с ретраями и запасной моделью
# ==========================================
def _clean(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL)
    return text.strip()


def _post(payload: dict, timeout: float, retries: int = 2) -> Optional[str]:
    for attempt in range(retries + 1):
        try:
            r = requests.post(GROQ_URL, headers=HEADERS, json=payload, timeout=timeout)
        except requests.RequestException as e:
            print(f"Groq: сетевая ошибка ({payload.get('model')}): {e}")
            time.sleep(1 + attempt)
            continue

        if r.status_code == 200:
            try:
                return _clean(r.json()["choices"][0]["message"]["content"])
            except (KeyError, IndexError, ValueError):
                return None

        if r.status_code in (429, 500, 502, 503, 504):
            print(f"Groq: {r.status_code} ({payload.get('model')}), повтор {attempt + 1}")
            time.sleep(1.5 * (attempt + 1))
            continue

        print(f"Groq: {r.status_code} {r.text[:200]}")
        return None
    return None


def chat(messages: list, model: Optional[str] = None, temperature: float = 0.8,
         max_tokens: Optional[int] = None, timeout: float = 25,
         fallback: bool = True) -> Optional[str]:
    """Возвращает текст или None (никогда не возвращает текст ошибки)."""
    models = [model or MODEL_NAME]
    if fallback and FALLBACK_MODEL not in models:
        models.append(FALLBACK_MODEL)

    for m in models:
        payload = {"model": m, "messages": messages, "temperature": temperature}
        if max_tokens:
            payload["max_tokens"] = max_tokens
        out = _post(payload, timeout)
        if out:
            return out
    return None


def quick_ask(prompt: str, temperature: float = 0.8) -> Optional[str]:
    return chat([{"role": "user", "content": prompt}], temperature=temperature, timeout=20)


# ==========================================
# СИСТЕМНЫЙ ПРОМПТ
# ==========================================
def build_system_prompt(is_roleplay: bool, bot_mood: int, note: str = "") -> str:
    system = SYSTEM_PROMPT + STYLE_PROMPT
    system += ROLEPLAY_PROMPT if is_roleplay else CHAT_MODE_PROMPT

    memory = load_memory()
    if memory:
        system += f"\n\nВот что ты помнишь обо мне из прошлого:\n{memory}"

    if bot_mood < -50:
        system += "\n\nТВОЁ НАСТРОЕНИЕ: ты обижена. Отвечай сухо и коротко, без ласки, но не груби."
    elif bot_mood < -20:
        system += "\n\nТВОЁ НАСТРОЕНИЕ: ты в плохом настроении. Отвечай чуть грустно, саркастично, но не груби."
    elif bot_mood > 50:
        system += "\n\nТВОЁ НАСТРОЕНИЕ: ты в отличном настроении. Будь весёлой, ласковой и игривой."
    else:
        system += "\n\nТВОЁ НАСТРОЕНИЕ: нейтральное."

    system += f"\n\nТВОЁ СОСТОЯНИЕ СЕГОДНЯ: {daily_life_state()} Упоминай это только к слову, не в каждом сообщении."

    now = now_msk()
    is_weekend = "Да (выходной)" if now.weekday() >= 5 else "Нет (учебный день)"
    holiday = "Да (каникулы!)" if check_holiday() else "Нет"
    system += (
        f"\n\nВАЖНАЯ ИНФОРМАЦИЯ: сейчас {now.strftime('%H:%M')} ({time_of_day(now.hour)}) по Москве. "
        f"Сегодня {weekday_name()}. Выходной: {is_weekend}. Каникулы: {holiday}. "
        f"Учитывай это в общении."
    )

    if is_school_time():
        system += (
            "\n\nСЕЙЧАС: ты на уроках в школе и пишешь украдкой, под партой. "
            "Отвечай очень коротко и можешь упомянуть, что тебя могут спалить."
        )

    if note:
        system += f"\n\n{note}"
    return system


# ==========================================
# ОСНОВНОЙ ОТВЕТ
# ==========================================
def get_ai_response(user_text: str, history: list, is_roleplay: bool = False,
                    bot_mood: int = 50, note: str = "") -> Optional[str]:
    """Ответ Nova или None, если API недоступен."""
    extra = note

    if len(user_text.split()) <= 2 and "\n" not in user_text:
        extra += "\n\nПРИМЕЧАНИЕ: я только что ответил очень коротко. Прояви заботу или пошути."

    if user_text.strip().lower() in ACK_PHRASES:
        extra += (
            "\n\nПРИМЕЧАНИЕ: я только что сказал дежурную фразу. "
            "Не нужно меня спасать или жалеть. Просто ответь легко или задай отвлечённый вопрос."
        )

    recent = history[-HISTORY_IN_PROMPT:]

    # Антиповтор: напоминаем модели её последние реплики
    last_replies = [m["content"] for m in recent if m["role"] == "assistant"][-3:]
    if last_replies:
        joined = " | ".join(r.replace("\n", " ")[:120] for r in last_replies)
        extra += f"\n\nТвои последние реплики (не повторяй их слова и шутки): {joined}"

    messages = [{"role": "system", "content": build_system_prompt(is_roleplay, bot_mood, extra.strip())}]
    messages.extend(recent)
    messages.append({"role": "user", "content": user_text})

    return chat(messages, temperature=0.85, max_tokens=700 if is_roleplay else 300)


# ==========================================
# НАСТРОЕНИЕ (быстрая модель, без запасной)
# ==========================================
def analyze_mood_change(user_text: str) -> int:
    if len(user_text.split()) <= 3:
        return 0

    prompt = (
        f'Проанализируй это сообщение: "{user_text[:500]}"\n'
        "Оцени, насколько оно эмоционально окрашено.\n"
        "Если это просто факт или фигура речи — ставь 0.\n"
        "Если человек радуется или ласков — от +10 до +30.\n"
        "Если грустит или злится — от -10 до -30.\n"
        "Отвечай ТОЛЬКО одним числом."
    )
    out = chat([{"role": "user", "content": prompt}], model=FAST_MODEL,
               temperature=0.1, max_tokens=10, timeout=10, fallback=False)
    if out:
        nums = re.findall(r"-?\d+", out)
        if nums:
            return max(-30, min(30, int(nums[0])))
    return 0


# ==========================================
# ПАМЯТЬ: факты из диалога
# ==========================================
def extract_facts(history_text: str) -> str:
    prompt = (
        "Проанализируй этот диалог. Выдели 3-5 важных деталей обо мне "
        "(планы, предпочтения, события, люди, настроение). "
        "Пиши кратко, по одной строке на факт, начиная с «- ». "
        "Если важного нет — ответь пустой строкой.\n\n"
        f"Диалог:\n{history_text[-6000:]}"
    )
    out = chat([{"role": "user", "content": prompt}], temperature=0.3, timeout=30)
    return out or ""


def compress_memory_nightly(history_text: str) -> str:
    return extract_facts(history_text)


# ==========================================
# МЕДИА
# ==========================================
def describe_image(base64_image: str) -> Optional[str]:
    prompt = "Коротко и по фактам опиши, что изображено на этой картинке (2-3 предложения)."
    data = {
        "model": VISION_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}},
            ],
        }],
    }
    return _post(data, timeout=30, retries=1)


def transcribe_audio(audio_bytes: bytes) -> Optional[str]:
    try:
        r = requests.post(
            GROQ_AUDIO_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            files={"file": ("voice.ogg", audio_bytes, "audio/ogg")},
            data={"model": WHISPER_MODEL, "language": "ru"},
            timeout=60,
        )
        if r.status_code == 200:
            return r.json().get("text", "").strip() or None
        print(f"Whisper: {r.status_code} {r.text[:200]}")
    except requests.RequestException as e:
        print(f"Whisper: сетевая ошибка: {e}")
    return None
