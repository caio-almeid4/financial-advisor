from pathlib import Path

import pytest

from src.ingestion.reader import find_input, read_input

_FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestFindInput:
    def test_prefers_pdf_over_txt(self, tmp_path):
        (tmp_path / "portfolio.pdf").write_bytes(b"%PDF-1.4")
        (tmp_path / "portfolio.txt").write_text("ignored")
        assert find_input(tmp_path, "portfolio").suffix == ".pdf"

    def test_falls_back_to_txt(self, tmp_path):
        (tmp_path / "portfolio.txt").write_text("hello")
        assert find_input(tmp_path, "portfolio").suffix == ".txt"

    def test_raises_when_neither_exists(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="portfolio"):
            find_input(tmp_path, "portfolio")

    def test_returns_correct_path(self, tmp_path):
        p = tmp_path / "macro.txt"
        p.write_text("content")
        assert find_input(tmp_path, "macro") == p


class TestReadInput:
    def test_reads_txt_content(self, tmp_path):
        p = tmp_path / "doc.txt"
        p.write_text("hello world", encoding="utf-8")
        assert read_input(p) == "hello world"

    def test_reads_txt_utf8(self, tmp_path):
        p = tmp_path / "doc.txt"
        p.write_text("Ações R$ 27.812,04", encoding="utf-8")
        assert "Ações" in read_input(p)

    def test_reads_pdf_returns_nonempty_string(self):
        text = read_input(_FIXTURES / "sample.pdf")
        assert isinstance(text, str)
        assert len(text) > 0

    def test_reads_pdf_contains_expected_content(self):
        text = read_input(_FIXTURES / "sample.pdf")
        assert "LREN3" in text
        assert "27812.04" in text

    def test_reads_pdf_case_insensitive_extension(self, tmp_path):
        # .PDF (uppercase) should also be treated as PDF
        import shutil
        src = _FIXTURES / "sample.pdf"
        dst = tmp_path / "doc.PDF"
        shutil.copy(src, dst)
        text = read_input(dst)
        assert len(text) > 0
