from .models import Session


def get_default_session():
    session, _ = Session.objects.get_or_create(
        name="Default Session"
    )
    return session


from pathlib import Path

# Base directory where all Chroma DBs are stored
BASE_CHROMA_DIR = Path("data/chroma")


def get_session_path(session_name: str) -> str:
    """
    Returns the filesystem path for a given session's vector store.
    Creates the directory if it does not exist.
    """
    session_dir = BASE_CHROMA_DIR / session_name
    session_dir.mkdir(parents=True, exist_ok=True)
    return str(session_dir)
