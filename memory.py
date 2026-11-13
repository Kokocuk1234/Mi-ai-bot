import os
import json
import threading
import datetime

from config import MEMORY_FILE, HISTORY_FILE, DATA_DIR, MEMORY_MAX_CHARS

_file_lock = threading.Lock()


def ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


# ==========================================
# ДОЛГАЯ ПАМЯТЬ (факты)
# ==========================================
def load_memory(max_chars: int = MEMORY_MAX_CHARS) -> str:
    """Возвращает хвост памяти (самые свежие факты), чтобы не раздувать промпт."""
    ensure_dir()
    with _file_lock:
        if not os.path.exists(MEMORY_FILE):
            return ""
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = f.read()
    return data[-max_chars:] if len(data) > max_chars else data


def save_memory(fact: str):
    ensure_dir()
    with _file_lock:
        with open(MEMORY_FILE, "a", encoding="utf-8") as f:
            f.write(fact.strip() + "\n")


def clear_memory():
    ensure_dir()
    with _file_lock:
        open(MEMORY_FILE, "w", encoding="utf-8").close()


def save_daily_facts(facts: str):
    date = datetime.datetime.now().strftime("%Y-%m-%d")
    save_memory(f"--- Факты от {date} ---\n{facts}")


# ==========================================
# ИСТОРИЯ ДИАЛОГА (переживает перезапуск)
# ==========================================
def load_history() -> list:
    ensure_dir()
    with _file_lock:
        if not os.path.exists(HISTORY_FILE):
            return []
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []


def save_history(history: list):
    ensure_dir()
    tmp = HISTORY_FILE + ".tmp"
    with _file_lock:
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False)
            os.replace(tmp, HISTORY_FILE)
        except OSError as e:
            print(f"Ошибка сохранения истории: {e}")
