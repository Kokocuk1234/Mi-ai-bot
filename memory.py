import os
import datetime
from config import MEMORY_FILE

def ensure_dir():
    os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)

def load_memory() -> str:
    ensure_dir()
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return f.read()
    return ""

def save_memory(fact: str):
    ensure_dir()
    with open(MEMORY_FILE, "a", encoding="utf-8") as f:
        f.write(fact + "\n")

def clear_memory():
    ensure_dir()
    open(MEMORY_FILE, "w").close()

def save_daily_facts(facts: str):
    save_memory(f"--- Факты от {datetime.datetime.now().strftime('%Y-%m-%d')} ---\n{facts}")
