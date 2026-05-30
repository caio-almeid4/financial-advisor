import base64
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from src.analysis.models import AllocationStatus, AssetReturn, PortfolioAnalysis, WatchlistItem
from src.llm.models import AssetRecommendation, PortfolioRecommendations
from src.report.charts import allocation_chart, returns_chart
from src.report.generator import (
    _slugify, _split_paragraphs,
    generate_report, generate_advisor_report, generate_web_report,
)


# --- Fixtures ---

def make_analysis() -> PortfolioAnalysis:
    return PortfolioAnalysis(
        client_name="Albert da Silva",
        reference_month="abril de 2025",
        total_invested=312186.20,
        available_balance=74672.62,
        total_patrimony=386858.82,
        investable_balance=55000.0,
        liquidity_buffer_pct=0.05,
        advisor_name="Antonio Bicudo",
        advisor_code="A7699",
        assets=[
            AssetReturn(name="LREN3", asset_class="acoes", allocation_pct=5.0,
                        monthly_return_pct=2.3, return_since_inception_pct=-10.0,
                        monthly_vs_cdi=1.4, investment_date="22/04/2021"),
            AssetReturn(name="Riza Lotus Advisory", asset_class="renda_fixa", allocation_pct=30.0,
                        monthly_return_pct=None, return_since_inception_pct=15.5,
                        monthly_vs_cdi=None, investment_date="22/04/2021"),
        ],
        portfolio_monthly_return_pct=None,
        cdi_monthly_pct=0.89,
        ipca_monthly_pct=0.43,
        ibovespa_monthly_pct=-1.5,
        allocation_status=[
            AllocationStatus(asset_class="acoes", current_pct=0.19, target_pct=0.20, gap_pct=-0.01),
            AllocationStatus(asset_class="renda_fixa", current_pct=0.50, target_pct=0.45, gap_pct=0.05),
            AllocationStatus(asset_class="fundos_multimercado", current_pct=0.20, target_pct=0.20, gap_pct=0.0),
            AllocationStatus(asset_class="fundos_acoes", current_pct=0.11, target_pct=0.15, gap_pct=-0.04),
        ],
        flags=["HAPV3 acumula -74.6% desde a compra"],
        watchlist=[
            WatchlistItem(ticker="ITUB4", current_price=27.8, monthly_return_pct=3.3, in_portfolio=False),
        ],
    )


def make_recommendations() -> PortfolioRecommendations:
    return PortfolioRecommendations(
        reasoning="HAPV3 has accumulated a severe loss of -74.6% since inception.",
        observations=["Carteira com boa diversificação em renda fixa."],
        recommendations=[
            AssetRecommendation(action="considerar_venda", asset="HAPV3",
                                rationale="Perda severa desde a compra."),
            AssetRecommendation(action="aumentar", asset="fundos_acoes",
                                rationale="Subponderado vs. alvo por 4pp."),
        ],
        macro_impact="Selic alta favorece renda fixa.",
        overall_assessment="Carteira estável com oportunidades de rebalanceamento.",
    )


LETTER = """Prezado Albert,

Acompanhamos sua carteira com atenção ao longo de abril de 2025.

O CDI do mês foi de 0,89%, servindo como nossa referência principal.

Recomendamos revisitar a posição em HAPV3.

Estamos à disposição para conversar.

Atenciosamente,
Seu Assessor XP"""


# --- charts.py ---

class TestAllocationChart:
    def test_returns_valid_base64_png(self):
        b64 = allocation_chart(make_analysis())
        decoded = base64.b64decode(b64)
        assert decoded[:8] == b"\x89PNG\r\n\x1a\n"

    def test_all_asset_classes_present(self):
        b64 = allocation_chart(make_analysis())
        assert len(b64) > 100


class TestReturnsChart:
    def test_returns_valid_base64_png(self):
        b64 = returns_chart(make_analysis())
        decoded = base64.b64decode(b64)
        assert decoded[:8] == b"\x89PNG\r\n\x1a\n"

    def test_handles_none_monthly_return(self):
        b64 = returns_chart(make_analysis())
        assert len(b64) > 100


# --- generator helpers ---

class TestSlugify:
    def test_ascii_name(self):
        assert _slugify("Albert da Silva") == "albert_da_silva"

    def test_accented_month(self):
        assert _slugify("abril de 2025") == "abril_de_2025"

    def test_special_chars(self):
        assert _slugify("São Paulo!") == "sao_paulo"


class TestSplitParagraphs:
    def test_splits_on_blank_lines(self):
        paras = _split_paragraphs(LETTER)
        assert len(paras) >= 5

    def test_no_empty_paragraphs(self):
        paras = _split_paragraphs(LETTER)
        assert all(p.strip() for p in paras)


# --- integration: real artifact generation ---

@pytest.mark.integration
def test_generate_report_creates_pdf(tmp_path):
    pdf_path = generate_report(LETTER, make_analysis(), make_recommendations(), output_dir=tmp_path)
    assert pdf_path.exists()
    assert pdf_path.suffix == ".pdf"
    assert pdf_path.stat().st_size > 10_000
    assert "albert_da_silva" in pdf_path.name
    assert "abril_de_2025" in pdf_path.name


@pytest.mark.integration
def test_generate_advisor_report_creates_pdf(tmp_path):
    pdf_path = generate_advisor_report(LETTER, make_analysis(), make_recommendations(), output_dir=tmp_path)
    assert pdf_path.exists()
    assert pdf_path.suffix == ".pdf"
    assert pdf_path.stat().st_size > 5_000
    assert "advisor_" in pdf_path.name
    assert "albert_da_silva" in pdf_path.name


@pytest.mark.integration
def test_generate_web_report_creates_html(tmp_path):
    html_path = generate_web_report(LETTER, make_analysis(), make_recommendations(), output_dir=tmp_path)
    assert html_path.exists()
    assert html_path.suffix == ".html"
    content = html_path.read_text(encoding="utf-8")
    assert "chart.js" in content.lower()
    assert "Albert da Silva" in content
    assert "chartAllocation" in content
    assert "chartTimeline" in content
