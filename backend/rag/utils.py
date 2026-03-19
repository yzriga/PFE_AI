from .models import Session

from pathlib import Path
from django.conf import settings


def get_default_session():
    session, _ = Session.objects.get_or_create(
        name="Default Session"
    )
    return session


def get_or_create_session(session_name: str | None):
    normalized = (session_name or "").strip()
    if not normalized:
        return get_default_session()
    session, _ = Session.objects.get_or_create(name=normalized)
    return session


# Base directory for all Chroma vector stores.
# Reads from the CHROMA_PERSIST_DIR setting which itself comes from .env.
BASE_CHROMA_DIR = Path(getattr(settings, "CHROMA_PERSIST_DIR", "data/chroma"))


def get_session_path(session_name: str) -> str:
    """
    Returns the filesystem path for a given session's vector store.
    Creates the directory if it does not exist.
    """
    session_dir = BASE_CHROMA_DIR / session_name
    session_dir.mkdir(parents=True, exist_ok=True)
    return str(session_dir)


def normalize_filename(name: str) -> str:
    return Path(name).name.strip().lower()


def sanitize_text(value: str) -> str:
    if not isinstance(value, str):
        return value

    # PostgreSQL JSON/text fields reject embedded NUL bytes.
    return value.replace("\x00", "")


def sanitize_json_value(value):
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, list):
        return [sanitize_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {
            sanitize_json_value(key): sanitize_json_value(val)
            for key, val in value.items()
        }
    return value
