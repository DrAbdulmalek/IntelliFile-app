"""اختبارات مساعد الملفات الذكي (File Copilot)"""
import pytest
from unittest.mock import patch, MagicMock
from src.core.file_copilot import FileCopilot, Conversation, Message


class TestMessage:
    """اختبارات رسالة محادثة"""

    def test_create_message(self):
        msg = Message(role="user", content="ما هو تشخيص المريض؟")
        assert msg.role == "user"
        assert msg.content == "ما هو تشخيص المريض؟"
        assert msg.sources == []

    def test_to_dict(self):
        msg = Message(role="assistant", content="المريض مصاب بالسكري", sources=["/report.pdf"])
        d = msg.to_dict()
        assert d["role"] == "assistant"
        assert d["sources"] == ["/report.pdf"]


class TestConversation:
    """اختبارات محادثة"""

    def test_create_conversation(self):
        conv = Conversation()
        assert conv.id is not None
        assert len(conv.messages) == 0
        assert conv.title == ""

    def test_add_message(self):
        conv = Conversation()
        conv.add_message("user", "مرحباً")
        assert len(conv.messages) == 1
        assert conv.title == "مرحباً"

    def test_title_from_first_user_message(self):
        conv = Conversation()
        conv.add_message("user", "أريد تلخيص التقرير الطبي")
        assert "أريد تلخيص" in conv.title

    def test_last_message(self):
        conv = Conversation()
        conv.add_message("user", "سؤال")
        conv.add_message("assistant", "إجابة")
        assert conv.last_message.role == "assistant"

    def test_to_dict(self):
        conv = Conversation()
        conv.add_message("user", "test")
        d = conv.to_dict()
        assert "id" in d
        assert len(d["messages"]) == 1


class TestFileCopilot:
    """اختبارات مساعد الملفات"""

    def test_init(self):
        copilot = FileCopilot()
        assert copilot.ollama_url == "http://localhost:11434"
        assert copilot.ai_model == "llama3.2"

    def test_list_conversations_empty(self):
        copilot = FileCopilot()
        convs = copilot.list_conversations()
        assert convs == []

    def test_chat_without_ollama(self):
        """Test chat when Ollama is not available — should return graceful message."""
        copilot = FileCopilot(ollama_url="http://localhost:99999")
        result = copilot.chat("ما هو السكري؟")
        assert "response" in result
        assert "conversation_id" in result

    def test_conversation_persistence(self):
        copilot = FileCopilot()
        result = copilot.chat("سؤال أول", conversation_id=None)
        conv_id = result["conversation_id"]
        # Second message in same conversation
        result2 = copilot.chat("سؤال ثاني", conversation_id=conv_id)
        assert result2["conversation_id"] == conv_id

    def test_delete_conversation(self):
        copilot = FileCopilot()
        result = copilot.chat("test")
        conv_id = result["conversation_id"]
        deleted = copilot.delete_conversation(conv_id)
        assert deleted is True
        assert copilot.get_conversation(conv_id) is None

    def test_summarize_nonexistent_file(self):
        copilot = FileCopilot()
        summary = copilot.summarize_file("/nonexistent/file.pdf")
        assert "خطأ" in summary or "غير" in summary

    def test_generate_returns_clear_message_when_ollama_not_running(self):
        """When Ollama is not reachable on port 11434, _generate should fail fast
        with a clear Arabic message instead of waiting for the import + chat timeout."""
        copilot = FileCopilot()
        # Mock socket.connect_ex to simulate Ollama being down (non-zero return)
        with patch("socket.socket") as mock_socket_cls:
            mock_sock = MagicMock()
            mock_sock.connect_ex.return_value = 111  # ECONNREFUSED
            mock_socket_cls.return_value = mock_sock
            result = copilot._generate("ما هو السكري؟", context="")
            assert "Ollama غير مشغّل" in result or "11434" in result

    def test_generate_returns_context_when_ollama_down_but_context_present(self):
        """If Ollama is down but we have retrieved context, the response should
        include that context so the user sees something useful."""
        copilot = FileCopilot()
        with patch("socket.socket") as mock_socket_cls:
            mock_sock = MagicMock()
            mock_sock.connect_ex.return_value = 111  # ECONNREFUSED
            mock_socket_cls.return_value = mock_sock
            result = copilot._generate("ما هو السكري؟", context="السكري مرض مزمن")
            assert "السكري مرض مزمن" in result
