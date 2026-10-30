"""Settings from environment variables / a local .env file (never committed)."""
from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    chat_model: str = os.getenv("GEMINI_CHAT_MODEL", "gemini-3.5-flash")
    mongodb_uri: str = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    mongodb_db: str = os.getenv("MONGODB_DB", "fairshare")
    default_currency: str = os.getenv("DEFAULT_CURRENCY", "EGP")


settings = Settings()


def get_chat_model():
    """Gemini reads receipt photos and understands chat messages (English, Arabic, Franco-Arabic)."""
    if not (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")):
        raise RuntimeError("No Gemini API key found. Get a free key at https://aistudio.google.com/apikey "
                           "and add GOOGLE_API_KEY=your-key to the .env file (see .env.example).")
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(model=settings.chat_model, temperature=0)
