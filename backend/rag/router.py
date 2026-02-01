import re

TITLE_PATTERNS = [
    r"\btitle\b",
    r"\bpaper title\b",
    r"\bwhat is the title\b",
    r"\bname of (this|the) paper\b",
]

def is_title_question(question: str) -> bool:
    q = question.lower()
    return any(re.search(p, q) for p in TITLE_PATTERNS)


ABOUT_PATTERNS = [
    r"\bwhat is this paper about\b",
    r"\bwhat's this paper about\b",
    r"\bwhat does this paper do\b",
    r"\bsummar(y|ize) this paper\b",
    r"\boverview of (this|the) paper\b",
    r"\bmain idea of (this|the) paper\b",
    r"\bwhat is the paper about\b",
    r"\bwhat does the paper propose\b",
    r"\bwhat is proposed in this paper\b",
]


def is_about_paper_question(question: str) -> bool:
    q = question.lower().strip()
    return any(re.search(pattern, q) for pattern in ABOUT_PATTERNS)