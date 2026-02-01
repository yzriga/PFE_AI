import re

def extract_title_and_abstract(text: str):
    """
    Very simple and robust heuristic:
    - Title = first non-empty lines (up to 3)
    - Abstract = text following the word 'Abstract'
    """

    lines = [l.strip() for l in text.split("\n") if l.strip()]

    # Title heuristic
    title = " ".join(lines[:3]) if lines else None

    # Abstract heuristic
    abstract = None
    match = re.search(r"abstract\s*(.*)", text, re.IGNORECASE | re.DOTALL)
    if match:
        abstract = match.group(1).split("\n\n")[0].strip()

    return title, abstract
import re

def extract_title_and_abstract(text: str):
    """
    Very simple and robust heuristic:
    - Title = first non-empty lines (up to 3)
    - Abstract = text following the word 'Abstract'
    """

    lines = [l.strip() for l in text.split("\n") if l.strip()]

    # Title heuristic
    title = " ".join(lines[:3]) if lines else None

    # Abstract heuristic
    abstract = None
    match = re.search(r"abstract\s*(.*)", text, re.IGNORECASE | re.DOTALL)
    if match:
        abstract = match.group(1).split("\n\n")[0].strip()

    return title, abstract
