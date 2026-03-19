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

def is_page_count_question(q: str) -> bool:
    q = q.lower()
    return any(
        p in q
        for p in [
            "how many pages",
            "number of pages",
            "page count",
            "total pages"
        ]
    )


RESEARCH_KEYWORDS = {
    "paper", "papers", "study", "studies", "research", "literature", "evidence",
    "trial", "trials", "dataset", "datasets", "model", "models", "benchmark",
    "benchmarks", "method", "methods", "algorithm", "algorithms", "retrieval",
    "rag", "llm", "transformer", "transformers", "diffusion", "genomics",
    "cancer", "diabetes", "cardiology", "clinical", "therapy", "biomarker",
    "meta-analysis", "systematic", "review", "reviews", "nlp", "vision",
    "protein", "omics", "covid", "federated", "multimodal", "architecture",
    "attention", "bert", "gpt", "encoder", "decoder", "prompting", "alignment",
}

GENERAL_BROAD_PATTERNS = [
    r"^what is [a-z\s]+$",
    r"^explain [a-z\s]+$",
    r"^tell me about [a-z\s]+$",
    r"^how does [a-z\s]+ work$",
]


def is_specific_research_question(question: str) -> bool:
    q = (question or "").strip().lower()
    if len(q) < 18:
        return False
    has_explanatory_topic_form = any(
        q.startswith(prefix)
        for prefix in [
            "explain ",
            "describe ",
            "summarize ",
            "overview of ",
            "how does ",
            "how do ",
            "what are ",
        ]
    )
    has_domain_anchor = any(
        token in q
        for token in [
            "transformer", "rag", "retrieval", "attention", "bert", "gpt",
            "clinical", "dataset", "benchmark", "diffusion", "protein",
        ]
    )
    if any(re.match(pattern, q) for pattern in GENERAL_BROAD_PATTERNS) and not (
        has_explanatory_topic_form and has_domain_anchor
    ):
        return False
    if '"' in q or "'" in q:
        return True
    keyword_hits = sum(1 for token in RESEARCH_KEYWORDS if token in q)
    has_topic_structure = any(
        phrase in q
        for phrase in [
            "papers about",
            "papers on",
            "studies on",
            "studies about",
            "evidence for",
            "evidence on",
            "literature on",
            "recent work on",
            "research on",
            "compare",
            "effect of",
            "impact of",
            "for ",
        ]
    )
    return (
        keyword_hits >= 2
        or (keyword_hits >= 1 and has_topic_structure)
        or (has_explanatory_topic_form and has_domain_anchor)
    )
