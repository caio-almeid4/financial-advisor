from pathlib import Path

import pdfplumber


def find_input(directory: Path, stem: str) -> Path:
    """Return the first existing file matching <stem>.pdf or <stem>.txt in directory."""
    for ext in (".pdf", ".txt"):
        if (p := directory / f"{stem}{ext}").exists():
            return p
    raise FileNotFoundError(
        f"No input file for '{stem}' in {directory}. "
        f"Expected {stem}.pdf or {stem}.txt"
    )


def read_input(path: Path) -> str:
    """Read a .txt or .pdf file and return its text content."""
    if path.suffix.lower() == ".pdf":
        return _extract_pdf(path)
    return path.read_text(encoding="utf-8")


def _extract_pdf(path: Path) -> str:
    """Extract text from a digitally generated PDF using pdfplumber.

    Tables are formatted as pipe-delimited rows so the LLM sees column
    associations explicitly (e.g. "LREN3 | R$27,812.04 | 8.91% | -41,7%").
    Full page text is appended after tables; minor duplication is harmless.
    Pages are separated by a horizontal rule so the LLM can track pagination.
    """
    pages: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            parts: list[str] = []

            for table in page.extract_tables():
                rows = [
                    " | ".join(str(cell or "").strip() for cell in row)
                    for row in table
                    if any(cell for cell in row)
                ]
                if rows:
                    parts.append("\n".join(rows))

            text = page.extract_text()
            if text and text.strip():
                parts.append(text.strip())

            if parts:
                pages.append("\n\n".join(parts))

    return "\n\n---\n\n".join(pages)
