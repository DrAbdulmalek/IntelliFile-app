"""مساعد الملفات الذكي (File Copilot) — RAG-based chat with files

Features:
  - Chat with your files using RAG (Retrieval-Augmented Generation)
  - Context-aware conversations with file content as knowledge base
  - Multi-turn conversation support with memory
  - Arabic RTL support with medical domain awareness
  - Integration with HybridSearchEngine for better retrieval
  - Source citations from original files
  - Offline-first: works with local Ollama
"""

from __future__ import annotations

import logging
import socket
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """رسالة واحدة في المحادثة"""
    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: str = ""
    sources: list[str] = field(default_factory=list)  # file paths used as sources

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "sources": self.sources,
        }


@dataclass
class Conversation:
    """محادثة كاملة مع سياق"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    messages: list[Message] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    files_indexed: list[str] = field(default_factory=list)

    def add_message(self, role: str, content: str, sources: list[str] | None = None):
        self.messages.append(Message(
            role=role,
            content=content,
            timestamp=datetime.now().isoformat(),
            sources=sources or [],
        ))
        if not self.title and role == "user":
            self.title = content[:50] + ("..." if len(content) > 50 else "")

    @property
    def last_message(self) -> Optional[Message]:
        return self.messages[-1] if self.messages else None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "messages": [m.to_dict() for m in self.messages],
            "created_at": self.created_at,
            "files_indexed": self.files_indexed,
        }


class FileCopilot:
    """مساعد الملفات الذكي — تحدث مع ملفاتك.

    Architecture:
      1. User asks a question about their files
      2. HybridSearchEngine retrieves relevant file content
      3. RAG engine generates an answer grounded in file content
      4. Source citations are attached to each response

    The copilot maintains conversation context so follow-up questions
    build on previous exchanges. It supports Arabic medical documents
    natively with RTL text handling.
    """

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        ai_model: str = "llama3.2",
        index_dir: str | None = None,
    ):
        self.ollama_url = ollama_url
        self.ai_model = ai_model
        self._index_dir = Path(index_dir) if index_dir else Path.home() / ".intellifile" / "copilot_index"
        self._conversations: dict[str, Conversation] = {}
        self._active_conversation: Optional[Conversation] = None
        self._hybrid_search = None
        self._rag_engine = None

    def _init_hybrid_search(self):
        """Lazy-load HybridSearchEngine."""
        if self._hybrid_search is not None:
            return
        try:
            from .hybrid_search import HybridSearchEngine
            self._hybrid_search = HybridSearchEngine()
            # Try loading existing index
            self._hybrid_search.load_index(str(self._index_dir))
            logger.info("تم تحميل HybridSearchEngine لـ FileCopilot")
        except Exception as exc:
            logger.warning(f"HybridSearchEngine غير متاح: {exc}")

    def _init_rag_engine(self):
        """Lazy-load RAGEngine."""
        if self._rag_engine is not None:
            return
        try:
            from .rag_engine import RAGEngine
            from .config import Config
            config = Config()
            config.ai_model = self.ai_model
            config.ollama_url = self.ollama_url
            self._rag_engine = RAGEngine(config=config)
            logger.info("تم تحميل RAGEngine لـ FileCopilot")
        except Exception as exc:
            logger.warning(f"RAGEngine غير متاح: {exc}")

    def index_files(self, filepaths: list[str]) -> int:
        """Index files for the copilot to reference.

        Args:
            filepaths: List of file paths to index

        Returns:
            Number of files successfully indexed
        """
        self._init_hybrid_search()
        self._init_rag_engine()

        total = 0

        # Index into hybrid search
        if self._hybrid_search:
            for fp in filepaths:
                try:
                    path = Path(fp)
                    if path.is_dir():
                        count = self._hybrid_search.index_files(fp)
                        total += count
                    elif path.is_file():
                        text = self._hybrid_search._extract_text(fp)
                        if text.strip():
                            total += 1
                except Exception as exc:
                    logger.debug(f"خطأ في فهرسة {fp}: {exc}")

        # Index into RAG engine
        if self._rag_engine:
            try:
                rag_count = self._rag_engine.index_documents(filepaths)
                logger.info(f"تم فهرسة {rag_count} مقطع في RAGEngine")
            except Exception as exc:
                logger.debug(f"خطأ في فهرسة RAG: {exc}")

        # Track indexed files in conversation
        if self._active_conversation:
            self._active_conversation.files_indexed.extend(filepaths)

        # Save hybrid search index
        if self._hybrid_search:
            try:
                self._index_dir.mkdir(parents=True, exist_ok=True)
                self._hybrid_search.save_index(str(self._index_dir))
            except Exception as exc:
                logger.debug(f"خطأ في حفظ الفهرس: {exc}")

        logger.info(f"تم فهرسة {total} ملف لـ FileCopilot")
        return total

    def chat(self, message: str, conversation_id: str | None = None) -> dict[str, Any]:
        """Send a message to the File Copilot and get a response.

        Args:
            message: User's question or request
            conversation_id: Optional conversation ID (creates new if None)

        Returns:
            Dict with response, sources, and conversation info
        """
        # Get or create conversation
        if conversation_id and conversation_id in self._conversations:
            conv = self._conversations[conversation_id]
        else:
            conv = Conversation()
            self._conversations[conv.id] = conv
        self._active_conversation = conv

        # Add user message
        conv.add_message("user", message)

        # Retrieve relevant content
        sources = self._retrieve(message)
        context = self._build_context(sources, conv)

        # Generate response
        response_text = self._generate(message, context)

        # Add assistant message with sources
        source_paths = [s.get("id", s.get("text", "")) for s in sources]
        conv.add_message("assistant", response_text, sources=source_paths)

        return {
            "response": response_text,
            "sources": sources,
            "conversation_id": conv.id,
            "message_count": len(conv.messages),
        }

    def _retrieve(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Retrieve relevant file content using hybrid search + RAG."""
        results = []

        # Try hybrid search first
        self._init_hybrid_search()
        if self._hybrid_search:
            try:
                results = self._hybrid_search.search(query, top_k=top_k)
            except Exception as exc:
                logger.debug(f"Hybrid search failed: {exc}")

        # Fallback to RAG semantic search
        if not results:
            self._init_rag_engine()
            if self._rag_engine:
                try:
                    rag_results = self._rag_engine.semantic_search(query, top_k=top_k)
                    for r in rag_results:
                        results.append({
                            "id": r.get("metadata", {}).get("source", ""),
                            "text": r.get("text", ""),
                            "rrf_score": 0.5,
                            "engine": "rag_semantic",
                        })
                except Exception as exc:
                    logger.debug(f"RAG search failed: {exc}")

        return results

    def _build_context(self, sources: list[dict], conv: Conversation) -> str:
        """Build the context string for the LLM prompt."""
        context_parts = []

        # File content from sources
        if sources:
            context_parts.append("=== محتوى الملفات ذات الصلة ===")
            for i, source in enumerate(sources[:5], 1):
                text = source.get("text", "")
                source_id = source.get("id", "مصدر غير معروف")
                context_parts.append(f"[مصدر {i}: {source_id}]\n{text[:800]}")
            context_parts.append("=== نهاية المحتوى ===\n")

        # Conversation history (last 6 messages)
        if len(conv.messages) > 1:
            context_parts.append("=== سياق المحادثة ===")
            for msg in conv.messages[-6:-1]:  # Exclude the current user message
                role = "المستخدم" if msg.role == "user" else "المساعد"
                context_parts.append(f"{role}: {msg.content[:300]}")
            context_parts.append("=== نهاية السياق ===\n")

        return "\n".join(context_parts)

    def _generate(self, query: str, context: str) -> str:
        """Generate a response using Ollama with file context."""
        # Pre-check: is Ollama actually reachable? Fail fast with a clear message
        # instead of waiting for the import + Client.chat() timeout.
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex(("127.0.0.1", 11434))
            sock.close()
            if result != 0:
                if context:
                    return (
                        "Ollama غير مشغّل على المنفذ 11434. "
                        "تم العثور على محتوى ذي صلة في الملفات:\n\n"
                        f"{context[:1000]}"
                    )
                return "Ollama غير مشغّل على المنفذ 11434. شغّله ثم أعد المحاولة."
        except Exception:
            # If the pre-check itself fails, fall through to the import-based path
            # below, which has its own ImportError / Exception handlers.
            pass

        system_prompt = (
            "أنت مساعد ذكي لإدارة الملفات الطبية. يمكنك:\n"
            "1. الإجابة عن أسئلة المستخدم بناءً على محتوى ملفاته\n"
            "2. تلخيص المستندات الطبية\n"
            "3. استخراج المعلومات المهمة\n"
            "4. المساعدة في تنظيم الملفات\n"
            "أجب بالعربية بدقة ووضوح. أشر إلى المصادر عند الاقتباس.\n"
            "إذا لم تجد الإجابة في الملفات، أخبر المستخدم بذلك بوضوح."
        )

        user_prompt = f"{context}\n\nسؤال المستخدم: {query}"

        try:
            import ollama
            client = ollama.Client(host=self.ollama_url)
            response = client.chat(self.ai_model, messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ])
            return response.get("message", {}).get("content", "لم أتمكن من إنشاء رد.")
        except ImportError:
            # Fallback: return retrieved context without LLM enhancement
            if context:
                return (
                    f"تم العثور على محتوى ذي صلة. "
                    f"لكن Ollama غير مثبت — لا يمكن إنشاء رد ذكي.\n\n"
                    f"المحتوى ذو الصلة:\n{context[:1000]}"
                )
            return "Ollama غير مثبت ولم يتم العثور على محتوى ذي صلة في الملفات."
        except Exception as exc:
            return f"خطأ في إنشاء الرد: {exc}"

    def get_conversation(self, conversation_id: str) -> Optional[Conversation]:
        """Get a conversation by ID."""
        return self._conversations.get(conversation_id)

    def list_conversations(self) -> list[dict[str, Any]]:
        """List all conversations."""
        return [
            {"id": c.id, "title": c.title, "messages": len(c.messages),
             "files": len(c.files_indexed)}
            for c in self._conversations.values()
        ]

    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation."""
        if conversation_id in self._conversations:
            del self._conversations[conversation_id]
            return True
        return False

    def summarize_file(self, filepath: str) -> str:
        """Generate a summary of a file's content."""
        try:
            text = ""
            path = Path(filepath)
            ext = path.suffix.lower()
            if ext in (".txt", ".md", ".csv", ".json"):
                text = path.read_text(encoding="utf-8", errors="ignore")[:4000]
            elif ext == ".pdf":
                import pdfplumber
                with pdfplumber.open(filepath) as pdf:
                    text = "\n".join(p.extract_text() or "" for p in pdf.pages)[:4000]
            elif ext == ".docx":
                from docx import Document
                doc = Document(filepath)
                text = "\n".join(p.text for p in doc.paragraphs)[:4000]

            if not text.strip():
                return "لم يتم العثور على محتوى نصي في الملف."

            try:
                import ollama
                client = ollama.Client(host=self.ollama_url)
                response = client.chat(self.ai_model, messages=[
                    {"role": "system", "content": "لخص النص التالي بإيجاز بالعربية. ركز على النقاط الرئيسية."},
                    {"role": "user", "content": text},
                ])
                return response.get("message", {}).get("content", "لم أتمكن من التلخيص.")
            except Exception:
                return text[:500] + "..." if len(text) > 500 else text

        except Exception as exc:
            return f"خطأ في قراءة الملف: {exc}"
