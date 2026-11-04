import re
import requests
from config import (
    GROQ_API_KEY, MODEL_NAME, VISION_MODEL,
    SYSTEM_PROMPT, ROLEPLAY_PROMPT,
)
from utils import now_msk, time_of_day, weekday_name, check_holiday
from memory import load_memory

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
HEADERS = {
    "Authorization": f"Bearer {GROQ_API_KEY}",
    "Content-Type": "application/json",
}

def build_system_prompt(is_roleplay: bool, bot_mood: int) -> str:
    system = SYSTEM_PROMPT

    if is_roleplay:
        system += ROLEPLAY_PROMPT
    else:
        system += "\n\nРЕЖИМ ОБЫЧНОГО ЧАТА: Общайся как в мессенджере, коротко."

    memory = load_memory()
    if memory:
        system += f"\n\nВот что ты помнишь обо мне из прошлого:\n{memory}"

    if bot_mood < -20:
        system += "\n\nТВОЕ НАСТРОЕНИЕ: Ты сейчас в плохом настроении. Отвечай чуть грустно, саркастично, но не груби."
    elif bot_mood > 50:
        system += "\n\nТВОЕ НАСТРОЕНИЕ: Ты сейчас в отличном настроении. Будь веселой, ласковой и игривой."
    else:
        system += "\n\nТВОЕ НАСТРОЕНИЕ: У тебя нейтральное настроение."

    now = now_msk()
    tod = time_of_day(now.hour)
    weekday = weekday_name()
    is_weekend = "Да (выходной)" if now.weekday() >= 5 else "Нет (учебный день)"
    holiday = "Да (каникулы!)" if check_holiday() else "Нет"

    system += (
        f"\n\nВАЖНАЯ ИНФОРМАЦИЯ: Сейчас {now.strftime('%H:%M')} ({tod}) по Москве. "
        f"Сегодня {weekday}. Выходной: {is_weekend}. Каникулы: {holiday}. "
        f"Учитывай это в общении."
    )
    return system

def get_ai_response(user_text: str, history: list, is_roleplay: bool = False, bot_mood: int = 50) -> str:
    system_content = build_system_prompt(is_roleplay, bot_mood)

    # Спец-пометки (сохраняем из старого кода)
    if len(user_text.split()) <= 2:
        system_content += "\n\nПРИМЕЧАНИЕ: Я только что ответил очень коротко. Прояви заботу или пошути."

    if user_text.strip().lower() in ["ну всякое бывает", "бывает", "ясно", "понятно", "ок", "хорошо"]:
        system_content += (
            "\n\nПРИМЕЧАНИЕ: Я только что сказал дежурную фразу. "
            "Не нужно меня спасать или жалеть. Просто ответь легко или задай отвлеченный вопрос."
        )

    messages = [{"role": "system", "content": system_content}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_text})

    try:
        r = requests.post(
            GROQ_URL, headers=HEADERS,
            json={"model": MODEL_NAME, "messages": messages, "temperature": 0.8},
            timeout=15,
        )
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
        return f"Ошибка API: {r.status_code}"
    except Exception as e:
        return f"Ошибка соединения: {e}"

def analyze_mood_change(user_text: str) -> int:
    if len(user_text.split()) <= 3:
        return 0

    prompt = (
        f'Проанализируй это сообщение: "{user_text}"\n'
        f"Оцени, насколько оно эмоционально окрашено.\n"
        f"Если это просто факт или фигура речи — ставь 0.\n"
        f"Если человек радуется — от +10 до +30.\n"
        f"Если грустит или злится — от -10 до -30.\n"
        f"Отвечай ТОЛЬКО одним числом."
    )
    try:
        r = requests.post(
            GROQ_URL, headers=HEADERS,
            json={"model": MODEL_NAME,
                  "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.1},
            timeout=15,
        )
        if r.status_code == 200:
            result = r.json()["choices"][0]["message"]["content"]
            nums = re.findall(r"-?\d+", result)
            if nums:
                return int(nums[0])
    except Exception:
        pass
    return 0

def compress_memory_nightly(history_text: str) -> str:
    prompt = (
        "Проанализируй этот диалог. Выдели 3-5 важных деталей обо мне. "
        "Напиши это в формате мини-историй.\n\n"
        f"Диалог:\n{history_text}"
    )
    try:
        r = requests.post(
            GROQ_URL, headers=HEADERS,
            json={"model": MODEL_NAME,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=30,
        )
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"Ошибка сжатия: {e}")
    return ""

def describe_image(base64_image: str) -> str:
    prompt = "Посмотри на это изображение. Опиши его."
    data = {
        "model": VISION_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
            ]
        }]
    }
    try:
        r = requests.post(GROQ_URL, headers=HEADERS, json=data, timeout=30)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
        return f"Ошибка распознавания: {r.status_code}"
    except Exception as e:
        return f"Ошибка: {e}"
