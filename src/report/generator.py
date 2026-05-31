import base64
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from src.analysis.models import PortfolioAnalysis
from src.llm.models import PortfolioRecommendations
from src.report.charts import allocation_chart, returns_chart

_TEMPLATE_DIR = Path(__file__).parent
_LOGO_PATH = Path(__file__).parents[2] / "assets" / "logo.png"
_OUTPUT_DIR = Path(__file__).parents[2] / "output"

_FOOTER_HTML = (
    '<div style="font-size:6pt;color:#999;width:100%;padding:0 24px;'
    'display:flex;justify-content:space-between;font-family:Helvetica,Arial,sans-serif">'
    '<span>Material de uso exclusivo do cliente. Não constitui oferta de valores '
    'mobiliários nem recomendação de investimento. Rentabilidade passada não representa '
    'garantia de retorno futuro. XP Investimentos CCTVM S.A. — CVM/ANCORD.</span>'
    '<span style="white-space:nowrap;margin-left:12px">'
    'Pág. <span class="pageNumber"></span> / <span class="totalPages"></span></span></div>'
)


def _logo_base64() -> str:
    return base64.b64encode(_LOGO_PATH.read_bytes()).decode("utf-8")


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _md_to_html(text: str) -> str:
    """Convert **bold** markdown to <strong> tags."""
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)


_SIGN_OFF_RE = re.compile(
    r"(atenciosamente|um abraço|abraços|cordialmente|até breve)", re.IGNORECASE
)


def _split_paragraphs(letter: str) -> list[str]:
    """Split letter on blank lines, converting markdown and stripping sign-off/placeholders."""
    paras = [p.strip() for p in re.split(r"\n{2,}", letter) if p.strip()]
    # Cut at any sign-off paragraph
    cutoff = next(
        (i for i, p in enumerate(paras) if _SIGN_OFF_RE.match(p)),
        len(paras),
    )
    paras = paras[:cutoff]
    # Remove paragraphs that are entirely a placeholder
    paras = [p for p in paras if not re.fullmatch(r"\[.*?\]", p, re.DOTALL)]
    # Strip inline placeholders like "[Assinatura do Consultor]" within a paragraph
    paras = [re.sub(r"\s*\[.*?\]", "", p).strip() for p in paras]
    # Drop any paragraph that became empty after stripping
    paras = [p for p in paras if p]
    # Hard cap: drop trailing paragraphs beyond the max to reduce fit iterations
    paras = paras[:_MAX_PARAGRAPHS]
    return [_md_to_html(p) for p in paras]


def _format_brl(value: float) -> str:
    """1234567.89 → 'R$ 1.234.567,89'"""
    formatted = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def _format_pct(value: float | None) -> tuple[str, str]:
    """Returns (formatted_str, css_class)."""
    if value is None:
        return "N/D", "neutral"
    sign = "+" if value > 0 else ""
    text = f"{sign}{value:.2f}%".replace(".", ",")
    css = "positive" if value > 0 else ("negative" if value < 0 else "neutral")
    return text, css


_A4_WIDTH_PX  = 794   # 210mm at 96dpi
_PAGE1_MAX_PX = 1020  # A4 height (1122px) minus 20mm bottom margin (76px), with 26px safety buffer

# Each step: (font-size, line-height)
_LETTER_SIZE_STEPS = [
    ("9.5pt", "1.65"),
    ("9pt",   "1.60"),
    ("8.5pt", "1.55"),
    ("8pt",   "1.50"),
    ("7.5pt", "1.45"),
    ("7pt",   "1.40"),
    ("6.5pt", "1.35"),
]
_MAX_PARAGRAPHS = 9  # hard cap: trim letter before even trying to fit


def _fit_letter_to_page(page) -> None:
    """Ensure the section-divider sits within page 1 so charts stay on page 2.

    Layer 1: progressively shrink font-size AND line-height together.
    Layer 2: if still overflowing at the smallest size, drop trailing paragraphs
             one at a time until it fits (hard cap on content, not on readability).
    No-op for templates without .letter or .section-divider (e.g. advisor PDF).
    """
    has_elements = page.evaluate(
        "() => !!(document.querySelector('.letter') && document.querySelector('.section-divider'))"
    )
    if not has_elements:
        return

    def _divider_top() -> float:
        return page.evaluate(
            "document.querySelector('.section-divider').getBoundingClientRect().top"
            " + window.scrollY"
        )

    # Layer 1: shrink font + line-height
    for font_size, line_height in _LETTER_SIZE_STEPS:
        page.evaluate(f"""
            const l = document.querySelector('.letter');
            l.style.fontSize   = '{font_size}';
            l.style.lineHeight = '{line_height}';
        """)
        if _divider_top() <= _PAGE1_MAX_PX:
            return

    # Layer 2: drop trailing paragraphs until it fits
    while _divider_top() > _PAGE1_MAX_PX:
        removed = page.evaluate("""
            const paras = document.querySelectorAll('.letter p');
            if (paras.length <= 1) return false;
            paras[paras.length - 1].remove();
            return true;
        """)
        if not removed:
            break  # single paragraph left — can't trim further, accept overflow


def _html_to_pdf(html: str, output_path: Path) -> None:
    """Render HTML to PDF using Playwright (Chromium). Supports full modern CSS."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": _A4_WIDTH_PX, "height": 1122})
        page.set_content(html, wait_until="networkidle")
        _fit_letter_to_page(page)
        page.pdf(
            path=str(output_path),
            format="A4",
            print_background=True,
            footer_template=_FOOTER_HTML,
            margin={"top": "0", "right": "0", "bottom": "20mm", "left": "0"},
        )
        browser.close()


_MONTH_PT = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril",
    5: "maio", 6: "junho", 7: "julho", 8: "agosto",
    9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro",
}


def _report_date_header() -> str:
    """Return current month and year for the PDF header, e.g. 'MAIO DE 2026'."""
    now = datetime.now()
    return f"{_MONTH_PT[now.month].upper()} DE {now.year}"


def _report_month_year_pt() -> str:
    """Return current month and year in lowercase Portuguese, e.g. 'maio de 2026'."""
    now = datetime.now()
    return f"{_MONTH_PT[now.month]} de {now.year}"


def _make_env() -> Environment:
    return Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True)


def generate_report(
    letter: str,
    analysis: PortfolioAnalysis,
    recommendations: PortfolioRecommendations,
    output_dir: Path | None = None,
) -> Path:
    out = output_dir or _OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)

    client_slug = _slugify(analysis.client_name)
    month_slug = _slugify(analysis.reference_month)
    pdf_path = out / f"report_{client_slug}_{month_slug}.pdf"

    ipca_monthly, _ = _format_pct(analysis.ipca_monthly_pct)
    cdi_monthly, _ = _format_pct(analysis.cdi_monthly_pct)
    ibovespa_monthly, ibov_class = _format_pct(analysis.ibovespa_monthly_pct)

    template = _make_env().get_template("template.html")
    html_content = template.render(
        logo_b64=_logo_base64(),
        report_date_header=_report_date_header(),
        reference_month=analysis.reference_month,
        client_name=analysis.client_name,
        advisor_name=analysis.advisor_name,
        advisor_code=analysis.advisor_code,
        total_invested=_format_brl(analysis.total_invested),
        ipca_monthly=ipca_monthly,
        cdi_monthly=cdi_monthly,
        ibovespa_monthly=ibovespa_monthly,
        ibov_class=ibov_class,
        letter_paragraphs=_split_paragraphs(letter),
        chart_allocation=allocation_chart(analysis),
        chart_returns=returns_chart(analysis),
    )

    _html_to_pdf(html_content, pdf_path)
    return pdf_path


def generate_advisor_report(
    letter: str,
    analysis: PortfolioAnalysis,
    recommendations: PortfolioRecommendations,
    output_dir: Path | None = None,
) -> Path:
    out = output_dir or _OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)

    client_slug = _slugify(analysis.client_name)
    month_slug = _slugify(analysis.reference_month)
    pdf_path = out / f"advisor_{client_slug}_{month_slug}.pdf"

    template = _make_env().get_template("advisor_template.html")
    html_content = template.render(
        logo_b64=_logo_base64(),
        reference_month=analysis.reference_month,
        report_month_year=_report_month_year_pt(),
        client_name=analysis.client_name,
        account=analysis.client_name,  # account not on PortfolioAnalysis; use name
        advisor_name=analysis.advisor_name,
        advisor_code=analysis.advisor_code,
        total_patrimony=_format_brl(analysis.total_patrimony),
        total_invested=_format_brl(analysis.total_invested),
        available_balance=_format_brl(analysis.available_balance),
        liquidity_buffer_pct=f"{analysis.liquidity_buffer_pct * 100:.0f}%",
        liquidity_reserve=_format_brl(analysis.total_patrimony * analysis.liquidity_buffer_pct),
        investable_balance=_format_brl(analysis.investable_balance),
        flags=analysis.flags,
        recommendations=[r.model_dump() for r in recommendations.recommendations],
        overall_assessment=recommendations.overall_assessment,
        macro_impact=recommendations.macro_impact,
    )

    _html_to_pdf(html_content, pdf_path)
    return pdf_path


