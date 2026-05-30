import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
LOG_DIR = Path(os.getenv("LOG_DIR", str(BASE_DIR / "logs")))
DB_PATH = Path(os.getenv("DB_PATH", str(DATA_DIR / "podcast_analyst.db")))

SUBTITLE_DIR = DATA_DIR / "subtitles"
REPORT_DIR = DATA_DIR / "reports"
TRANSCRIPT_CACHE_DIR = DATA_DIR / "transcripts" / "youtube"

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "mock")
LLM_MODEL = os.getenv("LLM_MODEL", "mock-v1")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# P2-C: Obsidian Vault export
OBSIDIAN_VAULT_PATH = os.getenv("OBSIDIAN_VAULT_PATH", "")
OBSIDIAN_EXPORT_ENABLED = os.getenv("OBSIDIAN_EXPORT_ENABLED", "false").lower() == "true"


def ensure_dirs() -> None:
    for d in [DATA_DIR, LOG_DIR, SUBTITLE_DIR, REPORT_DIR, TRANSCRIPT_CACHE_DIR]:
        d.mkdir(parents=True, exist_ok=True)