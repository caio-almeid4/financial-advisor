import base64
import json
import re
import unicodedata
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from src.analysis.models import PortfolioAnalysis
from src.llm.models import PortfolioRecommendations
from src.report.charts import allocation_chart, returns_chart

_TEMPLATE_DIR = Path(__file__).parent
_LOGO_PATH = Path(__file__).parents[2] / "XP_Investimentos_logo.png"
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


def _split_paragraphs(letter: str) -> list[str]:
    """Split letter on blank lines, converting markdown and stripping sign-off/placeholders."""
    paras = [p.strip() for p in re.split(r"\n{2,}", letter) if p.strip()]
    cutoff = next(
        (i for i, p in enumerate(paras) if re.match(r"atenciosamente", p, re.IGNORECASE)),
        len(paras),
    )
    paras = paras[:cutoff]
    paras = [p for p in paras if not re.fullmatch(r"\[.*?\]", p, re.DOTALL)]
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


def _html_to_pdf(html: str, output_path: Path) -> None:
    """Render HTML to PDF using Playwright (Chromium). Supports full modern CSS."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="networkidle")
        page.pdf(
            path=str(output_path),
            format="A4",
            print_background=True,
            footer_template=_FOOTER_HTML,
            margin={"top": "0", "right": "0", "bottom": "20mm", "left": "0"},
        )
        browser.close()


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


