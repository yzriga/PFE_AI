import logging
from typing import Dict, List, Any

from django.db.models import Q
from langchain_chroma import Chroma

from rag.models import Highlight, HighlightEmbedding, Session
from rag.services.ollama_client import create_embeddings
from rag.utils import get_session_path

logger = logging.getLogger(__name__)


class HighlightService:
    """Handles highlight embedding/indexing and session-level search."""

    collection_name = "highlights"

    def _get_vectordb(self, session_name: str) -> Chroma:
        return Chroma(
            collection_name=self.collection_name,
            persist_directory=get_session_path(session_name),
            embedding_function=create_embeddings(model="nomic-embed-text"),
        )

    def index_highlight(self, highlight: Highlight) -> str:
        session_name = highlight.document.session.name
        vectordb = self._get_vectordb(session_name)

        embedding_id = f"hl_{highlight.id}"
        metadata = {
            "highlight_id": highlight.id,
            "session": session_name,
            "document_id": highlight.document_id,
            "source": highlight.document.filename,
            "page": highlight.page,
            "tags": ",".join(highlight.tags or []),
        }

        vectordb.add_texts(
            texts=[highlight.text],
            metadatas=[metadata],
            ids=[embedding_id],
        )

        HighlightEmbedding.objects.update_or_create(
            highlight=highlight,
            defaults={"embedding_id": embedding_id},
        )
        return embedding_id

    def delete_highlight_embedding(self, highlight: Highlight) -> None:
        embedding = getattr(highlight, "embedding", None)
        if not embedding:
            return

        try:
            vectordb = self._get_vectordb(highlight.document.session.name)
            vectordb.delete(ids=[embedding.embedding_id])
        except Exception as exc:
            logger.warning(f"Failed deleting highlight embedding: {exc}")

    def search_highlights(
        self, session: Session, query: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        seen_ids = set()

        # 1) Semantic search (best for "supporting claim X"-style prompts)
        try:
            vectordb = self._get_vectordb(session.name)
            semantic = vectordb.similarity_search_with_relevance_scores(
                query,
                k=limit,
                filter={"session": session.name},
            )
            for doc, score in semantic:
                highlight_id = doc.metadata.get("highlight_id")
                if not highlight_id or highlight_id in seen_ids:
                    continue
                seen_ids.add(highlight_id)
                results.append(
                    {
                        "highlight_id": highlight_id,
                        "score": float(score),
                    }
                )
        except Exception as exc:
            logger.warning(f"Semantic highlight search failed: {exc}")

        # 2) Lexical fallback / complement
        lexical_qs = (
            Highlight.objects.select_related("document", "document__session")
            .filter(document__session=session)
            .filter(
                Q(text__icontains=query)
                | Q(note__icontains=query)
                | Q(tags__icontains=query)
            )[:limit]
        )

        for hl in lexical_qs:
            if hl.id in seen_ids:
                continue
            seen_ids.add(hl.id)
            results.append({"highlight_id": hl.id, "score": 0.0})

        # Hydrate in requested order
        hydrated: List[Dict[str, Any]] = []
        for row in results[:limit]:
            try:
                hl = Highlight.objects.select_related("document").get(
                    id=row["highlight_id"],
                    document__session=session,
                )
                hydrated.append(
                    {
                        "id": hl.id,
                        "document_id": hl.document_id,
                        "filename": hl.document.filename,
                        "page": hl.page,
                        "start_offset": hl.start_offset,
                        "end_offset": hl.end_offset,
                        "text": hl.text,
                        "note": hl.note,
                        "tags": hl.tags,
                        "score": round(row["score"], 4),
                        "created_at": hl.created_at,
                    }
                )
            except Highlight.DoesNotExist:
                continue

        return hydrated
