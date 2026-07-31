"""محرك البحث الهجين - يجمع بين BM25 والدلالي مع RRF

Hybrid Search Engine that combines:
  - BM25 (keyword-based, via rank_bm25)
  - Semantic (embedding-based, via sentence-transformers)
  - Reciprocal Rank Fusion (RRF) for score merging

Optimized for Arabic medical documents with RTL support.
"""

from __future__ import annotations

import json
import logging
import math
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Arabic text normalizer for better BM25 matching
_ARABIC_NORMALIZE_MAP = str.maketrans(
    "إأآىة",
    "ااايه",
)


def _normalize_arabic(text: str) -> str:
    """Normalize Arabic text for search: unify alef/yaa/taa marbuta."""
    return text.translate(_ARABIC_NORMALIZE_MAP)


def _tokenize(text: str) -> list[str]:
    """Tokenize text into words (Arabic + English aware)."""
    text = _normalize_arabic(text)
    # Split on non-alphanumeric (keeps Arabic and English words)
    tokens = re.findall(r"[\u0600-\u06FF\w]+", text.lower())
    return tokens


class BM25Engine:
    """Okapi BM25 engine for keyword-based search.

    Stores documents as token lists and computes BM25 scores.
    Supports Arabic text normalization out of the box.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._docs: list[str] = []          # raw text
        self._tokenized: list[list[str]] = []  # token lists
        self._df: dict[str, int] = {}        # document frequency
        self._avg_dl: float = 0.0
        self._N: int = 0

    def add_documents(self, documents: list[str]):
        """Add documents to the BM25 index."""
        for doc in documents:
            tokens = _tokenize(doc)
            self._docs.append(doc)
            self._tokenized.append(tokens)
            self._N += 1
            # Update document frequencies
            seen = set(tokens)
            for token in seen:
                self._df[token] = self._df.get(token, 0) + 1

        # Recompute average document length
        total = sum(len(t) for t in self._tokenized)
        self._avg_dl = total / max(self._N, 1)

    def search(self, query: str, top_k: int = 10) -> list[tuple[int, float]]:
        """Search and return (doc_index, score) pairs sorted by score desc."""
        query_tokens = _tokenize(query)
        if not query_tokens or not self._N:
            return []

        scores: list[tuple[int, float]] = []
        for idx, doc_tokens in enumerate(self._tokenized):
            score = self._score_document(query_tokens, doc_tokens)
            if score > 0:
                scores.append((idx, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def _score_document(self, query_tokens: list[str], doc_tokens: list[str]) -> float:
        """Compute BM25 score for a single document."""
        dl = len(doc_tokens)
        tf_map: dict[str, int] = {}
        for t in doc_tokens:
            tf_map[t] = tf_map.get(t, 0) + 1

        score = 0.0
        for qt in query_tokens:
            tf = tf_map.get(qt, 0)
            if tf == 0:
                continue
            df = self._df.get(qt, 0)
            idf = math.log((self._N - df + 0.5) / (df + 0.5) + 1.0)
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (1 - self.b + self.b * dl / max(self._avg_dl, 1e-8))
            score += idf * numerator / denominator
        return score

    @property
    def document_count(self) -> int:
        return self._N


class SemanticSearchEngineV2:
    """Enhanced semantic search with multilingual model for Arabic medical text.

    Uses sentence-transformers with a multilingual model optimized for
    Arabic content. Falls back gracefully when the library is unavailable.
    """

    def __init__(self, model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"):
        self.model_name = model_name
        self._model = None
        self._embeddings: dict[str, list[float]] = {}
        self._texts: dict[str, str] = {}

    def _load_model(self):
        if self._model is not None:
            return True
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
            logger.info(f"تم تحميل نموذج البحث الدلالي: {self.model_name}")
            return True
        except ImportError:
            logger.warning("sentence-transformers غير مثبت — البحث الدلالي غير متاح")
            return False
        except Exception as e:
            logger.error(f"خطأ في تحميل النموذج: {e}")
            return False

    def index_documents(self, documents: dict[str, str]) -> int:
        """Index documents: {doc_id: text}. Returns count of indexed docs."""
        if not self._load_model():
            return 0
        count = 0
        for doc_id, text in documents.items():
            if not text.strip():
                continue
            try:
                emb = self._model.encode(text, normalize_embeddings=True)
                self._embeddings[doc_id] = emb.tolist()
                self._texts[doc_id] = text
                count += 1
            except Exception as exc:
                logger.debug(f"خطأ في فهرسة {doc_id}: {exc}")
        logger.info(f"تم فهرسة {count} مستند دلالياً")
        return count

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Semantic search. Returns [(doc_id, score), ...]."""
        if not self._load_model() or not self._embeddings:
            return []
        import numpy as np
        try:
            q_emb = self._model.encode(query, normalize_embeddings=True)
            results = []
            for doc_id, emb_list in self._embeddings.items():
                sim = float(np.dot(q_emb, np.array(emb_list)))
                results.append((doc_id, sim))
            results.sort(key=lambda x: x[1], reverse=True)
            return results[:top_k]
        except Exception as exc:
            logger.error(f"خطأ في البحث الدلالي: {exc}")
            return []


class HybridSearchEngine:
    """Hybrid search combining BM25 + Semantic with Reciprocal Rank Fusion.

    Architecture:
      1. BM25 engine — keyword matching (fast, no model needed)
      2. Semantic engine — embedding similarity (needs sentence-transformers)
      3. RRF fusion — merge rankings from both engines

    The fusion formula (RRF):
        RRF_score(d) = Σ (1 / (k + rank_i(d)))
    where k=60 is a constant that reduces the impact of high rankings.

    This engine is optimized for Arabic medical document collections
    and supports RTL text natively.
    """

    def __init__(
        self,
        semantic_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        bm25_k1: float = 1.5,
        bm25_b: float = 0.75,
        rrf_k: int = 60,
        bm25_weight: float = 0.4,
        semantic_weight: float = 0.6,
    ):
        self.bm25 = BM25Engine(k1=bm25_k1, b=bm25_b)
        self.semantic = SemanticSearchEngineV2(model_name=semantic_model)
        self.rrf_k = rrf_k
        self.bm25_weight = bm25_weight
        self.semantic_weight = semantic_weight
        self._doc_ids: list[str] = []
        self._doc_texts: dict[str, str] = {}

    def index_files(self, directory: str, extensions: tuple[str, ...] | None = None) -> int:
        """Index files from a directory into both BM25 and semantic engines.

        Args:
            directory: Path to scan for files
            extensions: Optional tuple of extensions to include (e.g., (".pdf", ".txt"))

        Returns:
            Number of files successfully indexed
        """
        dir_path = Path(directory)
        if not dir_path.is_dir():
            logger.error(f"المجلد غير موجود: {directory}")
            return 0

        documents: dict[str, str] = {}
        texts_for_bm25: list[str] = []
        doc_ids_for_bm25: list[str] = []

        for item in dir_path.rglob("*"):
            if not item.is_file() or item.name.startswith("."):
                continue
            if extensions and item.suffix.lower() not in extensions:
                continue
            try:
                text = self._extract_text(str(item))
                if text.strip():
                    doc_id = str(item)
                    documents[doc_id] = text
                    texts_for_bm25.append(text)
                    doc_ids_for_bm25.append(doc_id)
                    self._doc_texts[doc_id] = text
            except Exception as exc:
                logger.debug(f"خطأ في قراءة {item}: {exc}")

        # Index into BM25
        self.bm25.add_documents(texts_for_bm25)
        self._doc_ids.extend(doc_ids_for_bm25)

        # Index into semantic engine
        semantic_count = self.semantic.index_documents(documents)

        total = len(documents)
        logger.info(
            f"تم فهرسة {total} ملف: BM25={total}, Semantic={semantic_count}"
        )
        return total

    def search(self, query: str, top_k: int = 10) -> list[dict[str, Any]]:
        """Hybrid search using RRF to merge BM25 + Semantic results.

        Args:
            query: Search query (Arabic or English)
            top_k: Number of results to return

        Returns:
            List of result dicts with keys: id, text, bm25_rank, semantic_rank, rrf_score
        """
        # BM25 results
        bm25_results = self.bm25.search(query, top_k=top_k * 3)
        bm25_ranks: dict[str, int] = {}
        for rank, (idx, _score) in enumerate(bm25_results, start=1):
            if idx < len(self._doc_ids):
                doc_id = self._doc_ids[idx]
                bm25_ranks[doc_id] = rank

        # Semantic results
        semantic_results = self.semantic.search(query, top_k=top_k * 3)
        semantic_ranks: dict[str, int] = {}
        for rank, (doc_id, _score) in enumerate(semantic_results, start=1):
            semantic_ranks[doc_id] = rank

        # RRF fusion
        all_doc_ids = set(bm25_ranks.keys()) | set(semantic_ranks.keys())
        rrf_scores: list[tuple[str, float, int, int]] = []

        for doc_id in all_doc_ids:
            bm25_rank = bm25_ranks.get(doc_id, 0)
            semantic_rank = semantic_ranks.get(doc_id, 0)

            # RRF score: sum of 1/(k + rank) for each engine that returned the doc
            score = 0.0
            if bm25_rank > 0:
                score += self.bm25_weight / (self.rrf_k + bm25_rank)
            if semantic_rank > 0:
                score += self.semantic_weight / (self.rrf_k + semantic_rank)

            rrf_scores.append((doc_id, score, bm25_rank, semantic_rank))

        rrf_scores.sort(key=lambda x: x[1], reverse=True)

        results = []
        for doc_id, rrf_score, bm25_rank, sem_rank in rrf_scores[:top_k]:
            results.append({
                "id": doc_id,
                "text": self._doc_texts.get(doc_id, "")[:500],
                "bm25_rank": bm25_rank,
                "semantic_rank": sem_rank,
                "rrf_score": round(rrf_score, 6),
                "engine": "hybrid_bm25+semantic_rrf",
            })
        return results

    def _extract_text(self, filepath: str) -> str:
        """Extract text content from a file for indexing."""
        path = Path(filepath)
        ext = path.suffix.lower()
        try:
            if ext in (".txt", ".md", ".csv", ".json", ".xml", ".yaml", ".yml",
                       ".py", ".js", ".ts", ".html", ".css", ".sh", ".log"):
                return path.read_text(encoding="utf-8", errors="ignore")[:4000]
            elif ext == ".pdf":
                try:
                    import pdfplumber
                    with pdfplumber.open(filepath) as pdf:
                        return "\n".join(p.extract_text() or "" for p in pdf.pages)[:4000]
                except ImportError:
                    pass
            elif ext in (".docx",):
                try:
                    from docx import Document
                    doc = Document(filepath)
                    return "\n".join(p.text for p in doc.paragraphs)[:4000]
                except ImportError:
                    pass
        except Exception as exc:
            logger.debug(f"لا يمكن قراءة {filepath}: {exc}")
        return ""  # was: path.name — indexing filenames as text is wrong

    def save_index(self, path: str):
        """Save the BM25 + semantic index to disk."""
        out = Path(path)
        out.mkdir(parents=True, exist_ok=True)
        data = {
            "doc_ids": self._doc_ids,
            "doc_texts": self._doc_texts,
            "bm25_docs": self.bm25._docs,
            "embeddings": self.semantic._embeddings,
        }
        with open(out / "hybrid_index.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        logger.info(f"تم حفظ الفهرس الهجين: {len(self._doc_ids)} مستند")

    def load_index(self, path: str) -> bool:
        """Load a previously saved index."""
        idx_file = Path(path) / "hybrid_index.json"
        if not idx_file.exists():
            return False
        try:
            with open(idx_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._doc_ids = data.get("doc_ids", [])
            self._doc_texts = data.get("doc_texts", {})
            # Rebuild BM25
            self.bm25 = BM25Engine()
            self.bm25.add_documents(data.get("bm25_docs", []))
            # Rebuild semantic embeddings (without re-encoding)
            self.semantic._embeddings = data.get("embeddings", {})
            logger.info(f"تم تحميل الفهرس الهجين: {len(self._doc_ids)} مستند")
            return True
        except Exception as exc:
            logger.error(f"خطأ في تحميل الفهرس: {exc}")
            return False
