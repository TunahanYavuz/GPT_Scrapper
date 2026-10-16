"""Environment-backed application settings."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


def env_path(name: str, default: str) -> Path:
    value = Path(os.getenv(name, default)).expanduser()
    return value if value.is_absolute() else (ROOT_DIR / value).resolve()


DATABASE_PATH = env_path("DATABASE_PATH", "data/campaigns.sqlite3")
SOURCES_PATH = env_path("SOURCES_PATH", "config/sources.json")
BROWSER_CDP_URL = os.getenv("BROWSER_CDP_URL", "http://127.0.0.1:9222").strip()
BROWSER_CDP_PORT = int(os.getenv("BROWSER_CDP_PORT", "9222"))
AUTO_LAUNCH_BROWSER = os.getenv("AUTO_LAUNCH_BROWSER", "false").lower() in {"1", "true", "yes"}
BROWSER_EXECUTABLE = os.getenv("BROWSER_EXECUTABLE", "").strip()
BROWSER_USER_DATA_DIR = env_path("BROWSER_USER_DATA_DIR", "browser-profile")
BROWSER_PROFILE_DIRECTORY = os.getenv("BROWSER_PROFILE_DIRECTORY", "Default").strip() or "Default"
NAVIGATION_TIMEOUT_MS = max(3000, min(120000, int(os.getenv("NAVIGATION_TIMEOUT_MS", "25000"))))
MAX_CAMPAIGNS_PER_SOURCE = max(1, min(500, int(os.getenv("MAX_CAMPAIGNS_PER_SOURCE", "100"))))
PAGE_DELAY_SECONDS = max(0.5, min(30.0, float(os.getenv("PAGE_DELAY_SECONDS", "1.5"))))
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
