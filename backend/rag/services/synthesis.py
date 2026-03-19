"""
Multi-document synthesis service for compare and literature review modes.

This service provides cross-document analysis capabilities:
- Compare mode: Identifies claims and stances across multiple papers
- Literature review mode: Generates structured reviews with citations
"""

import json
import re
from itertools import combinations
from typing import List, Dict, Any, Optional, Set
from collections import defaultdict
from rag.services.ollama_client import create_llm


class SynthesisService:
    """Service for multi-document analysis and synthesis."""

    def __init__(self, model: str = "mistral"):
        """
        Initialize synthesis service.
        """
        self.llm = create_llm(model=model)

    def _parse_compare_json(self, response: str) -> Optional[Dict[str, Any]]:
        """
        Parse and validate compare response JSON.
        """
        json_start = response.find("{")
        json_end = response.rfind("}") + 1
        if json_start < 0 or json_end <= json_start:
            return None

        candidate = response[json_start:json_end]
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return None

        claims = parsed.get("claims")
        if claims is None:
            return None
        if not isinstance(claims, list):
            return None

        # Soft normalization of expected shape
        normalized_claims = []
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            normalized_claims.append(
                {
                    "claim": claim.get("claim", ""),
                    "papers": claim.get("papers", []),
                }
            )
        parsed["claims"] = normalized_claims
        return parsed

    def _format_literature_review(self, topic: str, parsed: Dict[str, Any]) -> str:
        lines = [
            "1. Scope of Review",
            parsed.get("scope", f"This review synthesizes the selected papers on {topic}."),
            "",
            "2. Paper-by-Paper Focus",
        ]

        paper_summaries = parsed.get("paper_summaries", [])
        for paper in paper_summaries:
            paper_id = paper.get("paper_id", "unknown")
            focus = paper.get("focus", "")
            contribution = paper.get("contribution") or paper.get("contributions", "")
            lines.append(f"- {paper_id}: {focus}".strip())
            if contribution:
                lines.append(f"  Contribution: {contribution}")

        section_map = [
            ("3. Common Approaches Across Papers", parsed.get("common_approaches", [])),
            ("4. Important Differences Between Papers", parsed.get("important_differences", [])),
            ("5. Methodological Patterns", parsed.get("methodological_patterns", [])),
            ("6. Open Problems and Research Gaps", parsed.get("open_problems", [])),
            ("7. Practical Takeaways", parsed.get("practical_takeaways", [])),
        ]

        for title, items in section_map:
            lines.append("")
            lines.append(title)
            if items:
                for item in items:
                    lines.append(f"- {item}")
            else:
                lines.append("- The retrieved evidence did not support a confident synthesis for this section.")

        return "\n".join(lines).strip()

    def _format_incompatible_review(
        self,
        topic: str,
        parsed: Dict[str, Any],
        warning: str,
    ) -> str:
        lines = [
            "1. Review Fit Alert",
            warning,
            "",
            "2. Scope of Request",
            (
                parsed.get("scope")
                or f'The selected papers do not form a coherent literature review set for "{topic}".'
            ),
            "",
            "3. Paper-by-Paper Focus",
        ]

        for paper in parsed.get("paper_summaries", []):
            paper_id = paper.get("paper_id", "unknown")
            focus = paper.get("focus", "")
            contribution = paper.get("contribution") or paper.get("contributions", "")
            lines.append(f"- {paper_id}: {focus}".strip())
            if contribution:
                lines.append(f"  Contribution: {contribution}")

        lines.extend([
            "",
            "4. Why a Unified Review Is Limited",
        ])
        for item in parsed.get("fit_issues", []):
            lines.append(f"- {item}")

        lines.extend([
            "",
            "5. Recommended Next Step",
            parsed.get(
                "next_step",
                "Narrow the topic, remove unrelated papers, or use QA mode on each paper separately before attempting a literature review.",
            ),
        ])

        return "\n".join(lines).strip()

    def _invoke_text(self, prompt: str) -> str:
        response = self.llm.invoke(prompt)
        return response.strip() if isinstance(response, str) else str(response).strip()

    def _parse_tagged_block(self, response: str, expected_tags: List[str]) -> Dict[str, str]:
        parsed = {tag: "" for tag in expected_tags}
        current_tag = None

        for raw_line in response.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            matched_tag = None
            for tag in expected_tags:
                prefix = f"{tag}:"
                if line.upper().startswith(prefix):
                    matched_tag = tag
                    parsed[tag] = line[len(prefix):].strip()
                    current_tag = tag
                    break

            if matched_tag is None and current_tag is not None:
                parsed[current_tag] = f"{parsed[current_tag]} {line}".strip()

        return parsed

    def _fallback_paper_summary(self, source: str, source_docs: List[Any]) -> Dict[str, str]:
        snippets = [doc.page_content.strip() for doc in source_docs[:3] if doc.page_content.strip()]
        combined = " ".join(snippets)
        combined = combined[:400] if combined else "Retrieved evidence was limited."
        return {
            "paper_id": source,
            "focus": combined,
            "methods": combined,
            "contributions": combined,
            "limitations": "The retrieved snippets do not expose clear limitations for this paper.",
        }

    def _summarize_paper_for_review(self, source: str, source_docs: List[Any]) -> Dict[str, str]:
        context_lines = []
        for doc in source_docs[:4]:
            raw_page = doc.metadata.get("page", "?")
            page = raw_page + 1 if isinstance(raw_page, int) else raw_page
            context_lines.append(f"[Page {page}] {doc.page_content}")
        context = "\n".join(context_lines)

        prompt = f"""You are preparing a literature review note for a single paper.

Paper filename: {source}

Using ONLY the snippets below, write four short fields. Do not use generic hedging like
"this paper appears to" or "the text suggests". Be direct and academic.

Return plain text with exactly these labels:
FOCUS: one sentence on the main research direction or problem
METHODS: one sentence on the methods or technical approach
CONTRIBUTIONS: one sentence on the paper's main contribution
LIMITATIONS: one sentence on limitations, gaps, or unresolved issues; if not evident, say so explicitly

Snippets:
{context}
"""
        response = self._invoke_text(prompt)
        parsed = self._parse_tagged_block(
            response,
            ["FOCUS", "METHODS", "CONTRIBUTIONS", "LIMITATIONS"],
        )
        if not parsed["FOCUS"] or not parsed["METHODS"] or not parsed["CONTRIBUTIONS"]:
            return self._fallback_paper_summary(source, source_docs)

        return {
            "paper_id": source,
            "focus": parsed["FOCUS"],
            "methods": parsed["METHODS"],
            "contributions": parsed["CONTRIBUTIONS"],
            "limitations": parsed["LIMITATIONS"] or "The retrieved snippets do not expose clear limitations for this paper.",
        }

    def _parse_bullets(self, response: str) -> List[str]:
        bullets = []
        for raw_line in response.splitlines():
            line = raw_line.strip()
            if line.startswith("- "):
                bullets.append(line[2:].strip())
            elif line.startswith("* "):
                bullets.append(line[2:].strip())
        return [bullet for bullet in bullets if bullet]

    def _normalize_tokens(self, text: str) -> Set[str]:
        stopwords = {
            "a", "an", "and", "are", "as", "at", "be", "based", "by", "for",
            "from", "in", "into", "is", "it", "of", "on", "or", "paper",
            "papers", "review", "reviews", "study", "studies", "that", "the",
            "their", "this", "to", "uses", "using", "with",
        }
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        return {token for token in tokens if len(token) > 2 and token not in stopwords}

    def _jaccard(self, left: Set[str], right: Set[str]) -> float:
        if not left or not right:
            return 0.0
        union = left | right
        if not union:
            return 0.0
        return len(left & right) / len(union)

    def assess_review_set(
        self,
        topic: str,
        paper_summaries: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        topic_tokens = self._normalize_tokens(topic)
        paper_tokens = {}
        topic_relevance = {}
        fit_issues = []

        for summary in paper_summaries:
            paper_id = summary.get("paper_id", "unknown")
            summary_text = " ".join(
                [
                    summary.get("focus", ""),
                    summary.get("methods", ""),
                    summary.get("contributions", ""),
                    summary.get("limitations", ""),
                ]
            )
            tokens = self._normalize_tokens(summary_text)
            paper_tokens[paper_id] = tokens

            if topic_tokens:
                overlap = len(tokens & topic_tokens)
                relevance = overlap / max(len(topic_tokens), 1)
            else:
                relevance = 0.5
            topic_relevance[paper_id] = round(relevance, 3)

        overlaps = []
        for left_summary, right_summary in combinations(paper_summaries, 2):
            left_id = left_summary.get("paper_id", "unknown")
            right_id = right_summary.get("paper_id", "unknown")
            overlap = self._jaccard(
                paper_tokens.get(left_id, set()),
                paper_tokens.get(right_id, set()),
            )
            overlaps.append(
                {
                    "papers": [left_id, right_id],
                    "score": round(overlap, 3),
                }
            )

        pairwise_overlap = round(
            sum(item["score"] for item in overlaps) / len(overlaps),
            3,
        ) if overlaps else 0.0
        min_relevance = min(topic_relevance.values()) if topic_relevance else 0.0
        avg_relevance = round(
            sum(topic_relevance.values()) / len(topic_relevance),
            3,
        ) if topic_relevance else 0.0

        low_relevance_papers = [
            paper_id for paper_id, score in topic_relevance.items() if score < 0.12
        ]
        if low_relevance_papers:
            joined = ", ".join(low_relevance_papers)
            fit_issues.append(
                f"Low topic fit detected for {joined}; the retrieved evidence does not align strongly with the requested review topic."
            )
        if pairwise_overlap < 0.08:
            fit_issues.append(
                "The selected papers share very little topical overlap in their retrieved evidence, so cross-paper synthesis would be weak."
            )
        elif pairwise_overlap < 0.16:
            fit_issues.append(
                "The selected papers overlap only partially, so any cross-paper conclusions should be treated as tentative."
            )

        if low_relevance_papers or pairwise_overlap < 0.08 or avg_relevance < 0.18:
            review_status = "incompatible_sources"
        elif pairwise_overlap < 0.16 or min_relevance < 0.2:
            review_status = "warning_review"
        else:
            review_status = "normal_review"

        warning = ""
        if review_status == "warning_review":
            warning = (
                "The selected papers only partially overlap with the requested topic. "
                "Cross-paper conclusions are limited and should be read cautiously."
            )
        elif review_status == "incompatible_sources":
            warning = (
                "The selected papers do not support a reliable unified literature review for this topic. "
                "The response below highlights each paper separately and explains why synthesis is limited."
            )

        next_step = (
            "Refine the topic so it matches all selected papers, remove unrelated papers, or switch to QA mode for paper-specific questions."
        )
        if review_status == "warning_review":
            next_step = (
                "Consider narrowing the review topic or removing the least relevant paper if you want stronger cross-paper conclusions."
            )

        return {
            "review_status": review_status,
            "warning": warning,
            "topic_relevance": topic_relevance,
            "pairwise_overlap": pairwise_overlap,
            "pairwise_details": overlaps,
            "fit_issues": fit_issues,
            "next_step": next_step,
        }

    def _fallback_section_bullets(
        self,
        section_name: str,
        paper_summaries: List[Dict[str, str]],
    ) -> List[str]:
        if not paper_summaries:
            return ["The retrieved evidence did not support a confident synthesis for this section."]

        if section_name == "common_approaches":
            return [
                "Across the selected papers, the retrieved evidence shows a shared focus on closely related research directions, but the exact overlap remains limited in the available snippets."
            ]
        if section_name == "important_differences":
            return [
                f"{paper_summaries[0]['paper_id']} emphasizes {paper_summaries[0]['focus']}, whereas {paper_summaries[1]['paper_id']} emphasizes {paper_summaries[1]['focus']}."
                if len(paper_summaries) > 1
                else f"{paper_summaries[0]['paper_id']} is the only paper summarized in the retrieved evidence."
            ]
        if section_name == "methodological_patterns":
            return [
                f"{summary['paper_id']} uses {summary['methods']}"
                for summary in paper_summaries[:3]
            ]
        if section_name == "open_problems":
            return [
                f"{summary['paper_id']}: {summary['limitations']}"
                for summary in paper_summaries[:3]
            ]
        if section_name == "practical_takeaways":
            return [
                f"{summary['paper_id']}: {summary['contributions']}"
                for summary in paper_summaries[:3]
            ]
        return ["The retrieved evidence did not support a confident synthesis for this section."]

    def _synthesize_section(
        self,
        *,
        topic: str,
        section_name: str,
        instruction: str,
        paper_summaries: List[Dict[str, str]],
    ) -> List[str]:
        summaries_text = "\n".join(
            [
                (
                    f"- {summary['paper_id']}\n"
                    f"  Focus: {summary['focus']}\n"
                    f"  Methods: {summary['methods']}\n"
                    f"  Contributions: {summary['contributions']}\n"
                    f"  Limitations: {summary['limitations']}"
                )
                for summary in paper_summaries
            ]
        )
        prompt = f"""You are writing the "{section_name}" section of an academic literature review on "{topic}".

Paper summaries:
{summaries_text}

Task:
{instruction}

Rules:
- Return 2 to 4 bullets only.
- Every bullet must mention at least one filename.
- Prefer explicit comparisons across papers instead of isolated summaries.
- Do not use generic phrases like "the text provided appears to be".
- Do not output any heading or prose outside the bullets.
"""
        response = self._invoke_text(prompt)
        bullets = self._parse_bullets(response)
        if bullets:
            return bullets
        return self._fallback_section_bullets(section_name, paper_summaries)

    def compare_papers(
        self,
        question: str,
        docs: List[Any],
        sources: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Compare multiple papers on a specific topic.
        """
        if not docs:
            return {
                "topic": question,
                "claims": [],
                "message": "No documents found to compare"
            }

        # Group documents by source
        docs_by_source = defaultdict(list)
        for doc in docs:
            source = doc.metadata.get("source", "unknown")
            docs_by_source[source].append(doc)

        # Build context with source-separated sections
        context_parts = []
        for source, source_docs in docs_by_source.items():
            source_context = f"\n\n--- Document: {source} ---\n"
            for doc in source_docs:
                raw_page = doc.metadata.get("page", "?")
                if isinstance(raw_page, int):
                    page = raw_page + 1
                else:
                    page = raw_page
                source_context += f"\n[Page {page}]: {doc.page_content}\n"
            context_parts.append(source_context)

        context = "\n".join(context_parts)

        prompt = f"""You are a scientific research analyst comparing multiple papers.
It is CRITICAL that you distinguish between the different papers listed below.
The user is asking: "{question}"

Analyze the documents below and identify key claims.
For each claim, identify:
1. What the claim states
2. Which papers support, contradict, or remain neutral on this claim. Refer to papers EXPLICITLY by their filenames.
3. Specific evidence (page numbers and excerpts) from each paper.

Documents provided:
{context}

Output your analysis in the following JSON format:
{{
  "claims": [
    {{
      "claim": "Clear statement of the claim",
      "papers": [
        {{
          "paper_id": "filename.pdf",
          "stance": "supports|contradicts|neutral",
          "evidence": [
            {{
              "page": 5,
              "excerpt": "Relevant quote from the paper"
            }}
          ]
        }}
      ]
    }}
  ]
}}

If only one paper is provided in the context, clearly state that in a "message" field in your JSON, but still try to provide claims from that single paper. However, if multiple papers are present, you MUST compare them.

Include 3-5 major claims. Focus on contrasting findings.

JSON OUTPUT:
"""
        response = self.llm.invoke(prompt)
        parsed = self._parse_compare_json(response)

        # Retry once with stricter instruction if needed
        if parsed is None:
            repair_prompt = (
                "Return ONLY valid JSON with this schema:\n"
                '{"claims":[{"claim":"...","papers":[{"paper_id":"...","stance":"supports|contradicts|neutral","evidence":[{"page":1,"excerpt":"..."}]}]}],'
                '"message":"optional"}\n\n'
                f"Original output to fix:\n{response}"
            )
            repaired = self.llm.invoke(repair_prompt)
            parsed = self._parse_compare_json(repaired)

        if parsed is None:
            return {
                "topic": question,
                "claims": [],
                "message": "Could not produce a structured comparison. Try narrowing the question.",
                "num_papers": len(docs_by_source),
                "sources": list(docs_by_source.keys()),
            }

        return {
            "topic": question,
            "claims": parsed.get("claims", []),
            "message": parsed.get("message", ""),
            "num_papers": len(docs_by_source),
            "sources": list(docs_by_source.keys())
        }

    def generate_literature_review(
        self,
        topic: str,
        docs: List[Any],
        sources: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Generate a structured literature review.
        """
        if not docs:
            return {
                "topic": topic,
                "content": "No documents found to review"
            }

        docs_by_source = defaultdict(list)
        for doc in docs:
            docs_by_source[doc.metadata.get("source", "unknown")].append(doc)

        context_parts = []
        for source, source_docs in docs_by_source.items():
            section_lines = [f"--- PAPER: {source} ---"]
            for doc in source_docs:
                raw_page = doc.metadata.get("page", "?")
                page = raw_page + 1 if isinstance(raw_page, int) else raw_page
                section_lines.append(f"[Page {page}] {doc.page_content}")
            context_parts.append("\n".join(section_lines))

        paper_summaries = [
            self._summarize_paper_for_review(source, source_docs)
            for source, source_docs in docs_by_source.items()
        ]
        review_fit = self.assess_review_set(topic, paper_summaries)

        if review_fit["review_status"] == "incompatible_sources":
            scope = (
                f'The selected papers were evaluated against the requested topic "{topic}", '
                "but they do not form a coherent review set."
            )
            parsed = {
                "scope": scope,
                "paper_summaries": paper_summaries,
                "fit_issues": review_fit["fit_issues"],
                "next_step": review_fit["next_step"],
            }
            final_content = self._format_incompatible_review(
                topic,
                parsed,
                review_fit["warning"],
            )
            return {
                "topic": topic,
                "title": f"Literature Review: {topic}",
                "content": final_content,
                "num_sources": len(docs_by_source),
                "structured_review": parsed,
                "review_status": review_fit["review_status"],
                "warning": review_fit["warning"],
                "review_diagnostics": review_fit,
            }

        scope = (
            f"This review synthesizes {len(docs_by_source)} selected papers on {topic}. "
            f"Each paper is treated separately before drawing cross-paper conclusions."
        )
        if review_fit["review_status"] == "warning_review":
            scope = f"{scope} {review_fit['warning']}"
        parsed = {
            "scope": scope,
            "paper_summaries": paper_summaries,
            "common_approaches": self._synthesize_section(
                topic=topic,
                section_name="common_approaches",
                instruction="Identify the main research directions or shared approaches across the papers.",
                paper_summaries=paper_summaries,
            ),
            "important_differences": self._synthesize_section(
                topic=topic,
                section_name="important_differences",
                instruction="Explain the most important differences in focus, assumptions, or contribution across the papers.",
                paper_summaries=paper_summaries,
            ),
            "methodological_patterns": self._synthesize_section(
                topic=topic,
                section_name="methodological_patterns",
                instruction="Summarize recurring methodological patterns or design choices across the papers.",
                paper_summaries=paper_summaries,
            ),
            "open_problems": self._synthesize_section(
                topic=topic,
                section_name="open_problems",
                instruction="Identify unresolved issues, limitations, or open questions across the papers.",
                paper_summaries=paper_summaries,
            ),
            "practical_takeaways": self._synthesize_section(
                topic=topic,
                section_name="practical_takeaways",
                instruction="Provide practical takeaways about where the field is moving based on the selected papers.",
                paper_summaries=paper_summaries,
            ),
        }

        final_content = self._format_literature_review(topic, parsed)

        return {
            "topic": topic,
            "title": f"Literature Review: {topic}",
            "content": final_content,
            "num_sources": len(docs_by_source),
            "structured_review": parsed,
            "review_status": review_fit["review_status"],
            "warning": review_fit["warning"],
            "review_diagnostics": review_fit,
        }
