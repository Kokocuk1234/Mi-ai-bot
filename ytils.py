import datetime
import random
import re

def now_msk() -> datetime.datetime:
    return datetime.datetime.utcnow() + datetime.timedelta(hours=3)

def check_holiday() -> bool:
    now = now_msk()
    m, d = now.month, now.day
    if m == 10 and d >= 26: return True
    if m == 11 and d <= 6:  return True
    if m == 12 and d >= 28: return True
    if m == 1  and d <= 10: return True
    if m == 3  and d >= 24: return True
    if m == 4  and d <= 2:  return True
    if m in (6, 7, 8):      return True
    return False

def time_of_day(hour: int) -> str:
    if 5 <= hour < 12:  return "Утро"
    if 12 <= hour < 18: return "День"
    if 18 <= hour < 23: return "Вечер"
    return "Ночь"

def weekday_name() -> str:
    weekdays = ["Понедельник", "Вторник", "Среда", "Четверг",
                "Пятница", "Суббота", "Воскресенье"]
    return weekdays[now_msk().weekday()]

def split_messages(text: str) -> list[str]:
    """Разбивает ответ на 1-2 сообщения для эффекта живого чата."""
    text = re.sub(r'[^\w\s.,!?;:()\-*]', '', text).strip()
    if not text:
        return []

    sentences = re.split(r'(?<=[.!?])\s+', text)

    if len(sentences) == 1:
        if len(text) > 100 or random.random() < 0.3:
            words = text.split()
            if len(words) > 5:
                mid = len(words) // 2
                return [" ".join(words[:mid]), " ".join(words[mid:])]
        return [text]

    return sentences[:2]
