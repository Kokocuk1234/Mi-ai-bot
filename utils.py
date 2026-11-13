import datetime
import random
import re

MSK = datetime.timezone(datetime.timedelta(hours=3))


def now_msk() -> datetime.datetime:
    return datetime.datetime.now(MSK)


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


def is_school_time() -> bool:
    """Будний день, 8:00-15:00, не каникулы — она на уроках."""
    now = now_msk()
    return now.weekday() < 5 and 8 <= now.hour < 15 and not check_holiday()


# ==========================================
# «ЖИЗНЬ» NOVA: состояние дня (одно и то же весь день)
# ==========================================
LIFE_STATES = [
    "Ты сегодня не выспалась и немного вялая.",
    "Ты сегодня в приподнятом настроении, без особой причины.",
    "Ты всё утро слушаешь одну и ту же песню и не можешь остановиться.",
    "Ты слегка поссорилась с подругой и ещё думаешь об этом.",
    "Ты досматриваешь сериал и постоянно хочешь о нём рассказать.",
    "Ты замёрзла и сидишь, закутавшись в толстовку, с горячим чаем.",
    "Ты ленишься и откладываешь домашку на последний момент.",
    "Ты слегка нервничаешь из-за контрольной.",
    "Ты придумала странную идею и хочешь её обсудить.",
    "У тебя обычный спокойный день, ничего особенного.",
    "Тебе скучно, и ты ищешь, чем бы заняться.",
    "Ты немного грустишь, но не хочешь это показывать.",
]


def daily_life_state() -> str:
    rng = random.Random(now_msk().date().toordinal())
    return rng.choice(LIFE_STATES)


# ==========================================
# РАЗБИВКА ОТВЕТА НА СООБЩЕНИЯ
# ==========================================
def _merge_shortest(parts: list[str]) -> list[str]:
    i = min(range(len(parts) - 1), key=lambda k: len(parts[k]) + len(parts[k + 1]))
    return parts[:i] + [parts[i] + " " + parts[i + 1]] + parts[i + 2:]


def split_messages(text: str, roleplay: bool = False, max_parts: int = 3) -> list[str]:
    """Делит ответ на 1-3 сообщения. Ничего не вырезает и не теряет."""
    text = text.strip()
    if not text:
        return []

    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]

    # В РПГ не ломаем блоки *...* — режем только по строкам
    if roleplay:
        parts = paragraphs
    elif len(paragraphs) >= 2:
        parts = paragraphs
    else:
        parts = [s for s in re.split(r"(?<=[.!?…])\s+", text) if s.strip()]

    # Одно длинное предложение — делим по запятой ближе к середине
    if len(parts) == 1 and not roleplay and len(text) > 160:
        commas = [m.end() for m in re.finditer(r"[,;:—]\s", text)]
        if commas:
            mid = len(text) // 2
            cut = min(commas, key=lambda p: abs(p - mid))
            parts = [text[:cut].strip(), text[cut:].strip()]

    # Совсем короткое — часто лучше одним сообщением
    if len(parts) > 1 and sum(len(p) for p in parts) < 60 and random.random() < 0.5:
        parts = [" ".join(parts)]

    while len(parts) > max_parts:
        parts = _merge_shortest(parts)

    return parts


def typing_delay(text: str) -> float:
    """Сколько «печатает» сообщение."""
    return min(len(text) * 0.05, 3.0) + random.uniform(0.3, 0.9)
