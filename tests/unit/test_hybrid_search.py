"""اختبارات محرك البحث الهجين"""
import pytest
from src.core.hybrid_search import BM25Engine, SemanticSearchEngineV2, HybridSearchEngine, _normalize_arabic, _tokenize


class TestArabicNormalization:
    """اختبارات تطبيع النص العربي"""

    def test_normalize_alef(self):
        assert _normalize_arabic("إبراهيم") == "ابراهيم"
        assert _normalize_arabic("أحمد") == "احمد"
        assert _normalize_arabic("آدم") == "ادم"

    def test_normalize_taa_marbuta(self):
        assert _normalize_arabic("مدرسة") == "مدرسه"

    def test_normalize_yaa(self):
        assert _normalize_arabic("موسى") == "موسي"


class TestTokenize:
    """اختبارات تقسيم النص"""

    def test_arabic_tokens(self):
        tokens = _tokenize("المريض يعاني من كسر في عظم الفخذ")
        assert "المريض" in tokens
        assert "كسر" in tokens

    def test_english_tokens(self):
        tokens = _tokenize("patient has a fracture")
        assert "patient" in tokens
        assert "fracture" in tokens

    def test_mixed_tokens(self):
        tokens = _tokenize("Diabetes سكري")
        assert "diabetes" in tokens
        assert "سكري" in tokens


class TestBM25Engine:
    """اختبارات محرك BM25"""

    def test_add_documents(self):
        engine = BM25Engine()
        engine.add_documents([
            "المريض يعاني من كسر في عظم الفخذ",
            "تقرير أشعة صدر للمريض",
            "وصفة دواء باراسيتامول 500 ملغ",
        ])
        assert engine.document_count == 3

    def test_search_arabic(self):
        engine = BM25Engine()
        engine.add_documents([
            "المريض يعاني من كسر في عظم الفخذ",
            "تقرير أشعة صدر للمريض",
            "وصفة دواء باراسيتامول 500 ملغ",
        ])
        results = engine.search("كسر عظم")
        assert len(results) > 0
        # The first document should be the best match
        assert results[0][0] == 0

    def test_search_english(self):
        engine = BM25Engine()
        engine.add_documents([
            "Patient has a bone fracture",
            "Chest X-ray report",
            "Prescription paracetamol 500mg",
        ])
        results = engine.search("fracture")
        assert len(results) > 0
        assert results[0][0] == 0

    def test_empty_search(self):
        engine = BM25Engine()
        engine.add_documents(["مستند طبي"])
        results = engine.search("غير موجود")
        # May return 0 results if no match
        assert isinstance(results, list)

    def test_empty_engine(self):
        engine = BM25Engine()
        results = engine.search("أي شيء")
        assert results == []


class TestHybridSearchEngine:
    """اختبارات محرك البحث الهجين"""

    def test_init(self):
        engine = HybridSearchEngine()
        assert engine.bm25 is not None
        assert engine.semantic is not None
        assert engine.rrf_k == 60

    def test_extract_text_txt(self, tmp_path):
        # Create a temp text file
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("محتوى طبي عربي", encoding="utf-8")
        engine = HybridSearchEngine()
        text = engine._extract_text(str(txt_file))
        assert "محتوى طبي عربي" in text

    def test_extract_text_pdf_missing(self, tmp_path):
        # Non-existent PDF should return empty string (was: filename, which
        # indexed filenames as document text — see PR #39 Kimi review fix).
        engine = HybridSearchEngine()
        text = engine._extract_text(str(tmp_path / "nonexistent.pdf"))
        assert text == ""
