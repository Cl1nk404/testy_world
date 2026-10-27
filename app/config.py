import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "да", "on"}

GIGACHAT_CREDENTIALS = os.getenv("GIGACHAT_CREDENTIALS", "").strip()
GIGACHAT_MODEL = os.getenv("GIGACHAT_MODEL", "GigaChat-3-Ultra").strip()
GIGACHAT_SCOPE = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS").strip()
GIGACHAT_BASE_URL = os.getenv("GIGACHAT_BASE_URL", "https://api.giga.chat/v1").strip()
GIGACHAT_VERIFY_SSL_CERTS = env_bool("GIGACHAT_VERIFY_SSL_CERTS", True)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL", "").strip()
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow").strip()
POST_HOUR = int(os.getenv("POST_HOUR", "9"))
POST_MINUTE = int(os.getenv("POST_MINUTE", "0"))
DRY_RUN = env_bool("DRY_RUN", True)
ENABLE_IMAGE = env_bool("ENABLE_IMAGE", False)
DATABASE_PATH = ROOT / os.getenv("DATABASE_PATH", "data/recipes.db")
OUTPUT_DIR = ROOT / os.getenv("OUTPUT_DIR", "output")
LOG_DIR = ROOT / os.getenv("LOG_DIR", "logs")
PROMPT_PATH = ROOT / "prompts" / "recipe_post.txt"

for directory in (DATABASE_PATH.parent, OUTPUT_DIR, LOG_DIR):
    directory.mkdir(parents=True, exist_ok=True)
