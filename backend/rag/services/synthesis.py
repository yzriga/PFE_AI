"""
Multi-document synthesis service for compare and literature review modes.

This service provides cross-document analysis capabilities:
- Compare mode: Identifies claims and stances across multiple papers
- Literature review mode: Generates structured reviews with citations
"""

import json
from typing import List, Dict, Any, Optional
from langchain_ollama import OllamaLLM
from collections import defaultdict


class SynthesisService:
    """Service for multi-document analysis and synthesis."""
    
    def __init__(self, model: str = "mistral"):
        """
        Initialize synthesis service.
        
        Args:
            model: LLM model name (default: mistral)
        """
        self.llm = OllamaLLM(model=model)
    
    def compare_papers(
        self,
        question: str,
        docs: List[Any],
        sources: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Compare multiple papers on a specific topic.
        
        Analyzes documents to identify key claims and how different
        papers support, contradict, or remain neutral on each claim.
        
        Args:
            question: Topic or question to compare across papers
            docs: Retrieved document chunks from vector DB
            sources: Optional list of source filenames for filtering
        
        Returns:
            Dict with structure:
            {
                "topic": str,
                "claims": [{
                    "claim": str,
                    "papers": [{
                        "paper_id": str,
                        "stance": "supports" | "contradicts" | "neutral",
                        "evidence": [{
                            "page": int,
                            "excerpt": str,
                            "chunk_id": str
                        }]
                    }]
                }]
            }
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
                page = doc.metadata.get("page", "?")
                source_context += f"\n[Page {page}]: {doc.page_content}\n"
            context_parts.append(source_context)
        
        context = "\n".join(context_parts)
        
        prompt = f"""You are a scientific research analyst comparing multiple papers.

Analyze the documents below and identify key claims related to the topic: "{question}"

For each claim, identify:
1. What the claim states
2. Which papers support, contradict, or remain neutral on this claim
3. Specific evidence (page numbers and excerpts) from each paper

Documents:
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

Focus on factual claims and concrete evidence. Include 3-5 major claims.
"""
        
        response = self.llm.invoke(prompt)
        
        # Parse LLM response
        try:
            # Extract JSON from response (may have markdown wrappers)
            json_start = response.find("{")
            json_end = response.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                parsed = json.loads(json_str)
                
                return {
                    "topic": question,
                    "claims": parsed.get("claims", []),
                    "num_papers": len(docs_by_source),
                    "sources": list(docs_by_source.keys())
                }
            else:
                # No JSON found in response
                raise ValueError("No JSON structure found in LLM response")
        except (json.JSONDecodeError, ValueError) as e:
            # Fallback: return raw response if JSON parsing fails
            return {
                "topic": question,
                "claims": [],
                "raw_response": response,
                "error": f"Failed to parse JSON: {str(e)}",
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
        Generate a structured literature review from multiple papers.
        
        Creates a comprehensive review with:
        - Introduction outlining the topic
        - Thematic sections synthesizing findings
        - Proper citations to source papers
        
        Args:
            topic: Topic for the literature review
            docs: Retrieved document chunks from vector DB
            sources: Optional list of source filenames
        
        Returns:
            Dict with structure:
            {
                "title": str,
                "outline": [str],  # Section headings
                "sections": [{
                    "heading": str,
                    "paragraphs": [{
                        "text": str,
                        "citations": [{
                            "paper": str,
                            "page": int,
                            "excerpt_preview": str
                        }]
                    }]
                }]
            }
        """
        if not docs:
            return {
                "title": f"Literature Review: {topic}",
                "outline": [],
                "sections": [],
                "message": "No documents found for review"
            }
        
        # Group documents by source
        docs_by_source = defaultdict(list)
        for doc in docs:
            source = doc.metadata.get("source", "unknown")
            docs_by_source[source].append(doc)
        
        # Build context with source information
        context_parts = []
        for source, source_docs in docs_by_source.items():
            source_context = f"\n\n--- Paper: {source} ---\n"
            for doc in source_docs:
                page = doc.metadata.get("page", "?")
                source_context += f"\n[Page {page}]: {doc.page_content}\n"
            context_parts.append(source_context)
        
        context = "\n".join(context_parts)
        
        prompt = f"""You are a scientific writer creating a literature review.

Write a structured literature review on: "{topic}"

Use the documents below as sources. Your review should:
1. Synthesize findings across papers (don't just summarize each paper separately)
2. Organize content thematically (e.g., Methods, Results, Implications)
3. Include proper citations in the format [PaperName, p.X]
4. Be comprehensive but concise (3-5 sections, 2-3 paragraphs each)

Documents:
{context}

Output your review in the following JSON format:
{{
  "title": "Literature Review: [Topic]",
  "outline": ["Section 1 heading", "Section 2 heading", ...],
  "sections": [
    {{
      "heading": "Section 1 heading",
      "content": "Full text of section with citations like [filename.pdf, p.5]. Multiple paragraphs OK."
    }}
  ]
}}

Focus on synthesis, not just summary. Connect ideas across papers.
"""
        
        response = self.llm.invoke(prompt)
        
        # Parse LLM response
        try:
            # Extract JSON from response
            json_start = response.find("{")
            json_end = response.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                parsed = json.loads(json_str)
                
                # Convert content to paragraphs structure with citation extraction
                sections = []
                for section in parsed.get("sections", []):
                    heading = section.get("heading", "")
                    content = section.get("content", "")
                    
                    # Simple paragraph split
                    paragraphs = [
                        {"text": p.strip(), "citations": self._extract_citations(p)}
                        for p in content.split("\n\n")
                        if p.strip()
                    ]
                    
                    sections.append({
                        "heading": heading,
                        "paragraphs": paragraphs
                    })
                
                return {
                    "title": parsed.get("title", f"Literature Review: {topic}"),
                    "outline": parsed.get("outline", []),
                    "sections": sections,
                    "num_papers": len(docs_by_source),
                    "sources": list(docs_by_source.keys())
                }
            else:
                # No JSON found in response
                raise ValueError("No JSON structure found in LLM response")
        except (json.JSONDecodeError, ValueError) as e:
            # Fallback: return raw response
            return {
                "title": f"Literature Review: {topic}",
                "outline": [],
                "sections": [],
                "raw_response": response,
                "error": f"Failed to parse JSON: {str(e)}",
                "num_papers": len(docs_by_source),
                "sources": list(docs_by_source.keys())
            }
    
    def _extract_citations(self, text: str) -> List[Dict[str, Any]]:
        """
        Extract citations from text in format [filename.pdf, p.X].
        
        Args:
            text: Text containing citations
        
        Returns:
            List of citation dicts with paper and page
        """
        import re
        
        citations = []
        # Pattern: [filename.pdf, p.5] or [filename, p.5]
        pattern = r'\[([^,\]]+),\s*p\.(\d+)\]'
        
        for match in re.finditer(pattern, text):
            paper = match.group(1).strip()
            page = int(match.group(2))
            citations.append({
                "paper": paper,
                "page": page
            })
        
        return citations
