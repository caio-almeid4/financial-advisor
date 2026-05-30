import json
from unittest.mock import MagicMock, patch

import pytest

from src.analysis.models import AllocationStatus, AssetReturn, PortfolioAnalysis, WatchlistItem
from src.ingestion.models import MacroAnalysis, MacroProjections, RiskProfile, TargetAllocation
from src.llm.models import AssetRecommendation, PortfolioRecommendations
from src.llm.recommendations import _build_user_message as build_rec_message
from src.llm.recommendations import generate_recommendations
from src.llm.writer import _build_user_message as build_writer_message
from src.llm.writer import write_letter
from src.prompts import recommendations as rec_prompts
from src.prompts import writer as writer_prompts


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
            AssetReturn(name="HAPV3", asset_class="acoes", allocation_pct=1.97,
                        monthly_return_pct=76.4, return_since_inception_pct=-74.58,
                        monthly_vs_cdi=75.5, investment_date="02/11/2022"),
            AssetReturn(name="Riza Lotus", asset_class="renda_fixa", allocation_pct=30.81,
                        monthly_return_pct=None, return_since_inception_pct=15.51,
                        monthly_vs_cdi=None, investment_date="22/04/2021"),
        ],
        portfolio_monthly_return_pct=None,
        cdi_monthly_pct=0.89,
        ipca_monthly_pct=0.43,
        ibovespa_monthly_pct=-1.5,
        allocation_status=[
            AllocationStatus(asset_class="acoes", current_pct=0.19,
                             target_pct=0.20, gap_pct=-0.01),
        ],
        flags=["HAPV3 acumula -74.6% desde a compra"],
        watchlist=[
            WatchlistItem(ticker="ITUB4", current_price=27.8, monthly_return_pct=3.3, in_portfolio=False),
        ],
    )


def make_risk_profile() -> RiskProfile:
    return RiskProfile(
        client_name="Albert",
        classification="Moderado",
        description="Perfil moderado.",
        compatible_products=["Ações com dividendos", "Renda fixa BB+"],
        target_allocation=TargetAllocation(
            acoes_pct=0.20, renda_fixa_pct=0.45,
            fundos_multimercado_pct=0.20, fundos_acoes_pct=0.15,
        ),
    )


def make_macro() -> MacroAnalysis:
    return MacroAnalysis(
        date="2025-02-06",
        title="Brasil Macro Mensal",
        key_points=["Selic em 15.5%", "IPCA projetado em 6.1%"],
        projections=MacroProjections(
            ipca_2025=6.1, ipca_2026=4.5, selic_terminal=15.5,
            gdp_growth_2025=2.0, usd_brl_end_2025=6.20,
        ),
        editorial_summary="Cenário de juros altos e inflação persistente.",
    )


def make_recommendations() -> PortfolioRecommendations:
    return PortfolioRecommendations(
        reasoning="HAPV3 accumulated severe losses. Recommend reduction.",
        observations=["HAPV3 acumula -74.6% desde a compra"],
        recommendations=[
            AssetRecommendation(action="considerar_venda", asset="HAPV3",
                                rationale="Perda severa e desalinhamento com perfil moderado.")
        ],
        macro_impact="Selic alta favorece renda fixa.",
        overall_assessment="Carteira com desvios de alocação e posições problemáticas em ações.",
    )


def _mock_parsed(obj):
    message = MagicMock()
    message.parsed = obj
    choice = MagicMock()
    choice.message = message
    completion = MagicMock()
    completion.choices = [choice]
    return completion


def _mock_text(text: str):
    message = MagicMock()
    message.content = text
    choice = MagicMock()
    choice.message = message
    completion = MagicMock()
    completion.choices = [choice]
    return completion


# --- User message builders ---

class TestBuildRecMessage:
    def test_includes_portfolio_analysis(self):
        msg = build_rec_message(make_analysis(), make_risk_profile(), make_macro())
        data = json.loads(msg)
        assert "portfolio_analysis" in data
        assert data["portfolio_analysis"]["client_name"] == "Albert da Silva"

    def test_includes_risk_profile(self):
        msg = build_rec_message(make_analysis(), make_risk_profile(), make_macro())
        data = json.loads(msg)
        assert data["risk_profile"]["classification"] == "Moderado"

    def test_includes_macro_projections(self):
        msg = build_rec_message(make_analysis(), make_risk_profile(), make_macro())
        data = json.loads(msg)
        assert data["macro_context"]["projections"]["selic_terminal"] == 15.5

    def test_includes_key_points(self):
        msg = build_rec_message(make_analysis(), make_risk_profile(), make_macro())
        data = json.loads(msg)
        assert len(data["macro_context"]["key_points"]) == 2


class TestBuildWriterMessage:
    def test_includes_client_name(self):
        msg = build_writer_message(make_recommendations(), make_analysis())
        data = json.loads(msg)
        assert data["client_name"] == "Albert da Silva"

    def test_includes_benchmarks(self):
        msg = build_writer_message(make_recommendations(), make_analysis())
        data = json.loads(msg)
        assert data["cdi_monthly_pct"] == 0.89
        assert data["ibovespa_monthly_pct"] == -1.5

    def test_includes_recommendations(self):
        msg = build_writer_message(make_recommendations(), make_analysis())
        data = json.loads(msg)
        assert len(data["recommendations"]) == 1
        assert data["recommendations"][0]["action"] == "considerar_venda"


# --- generate_recommendations ---

class TestGenerateRecommendations:
    @patch("src.llm.recommendations.client")
    def test_returns_portfolio_recommendations(self, mock_client):
        mock_client.beta.chat.completions.parse.return_value = _mock_parsed(make_recommendations())
        result = generate_recommendations(make_analysis(), make_risk_profile(), make_macro())
        assert isinstance(result, PortfolioRecommendations)
        assert len(result.observations) > 0

    @patch("src.llm.recommendations.client")
    def test_uses_gpt4o(self, mock_client):
        mock_client.beta.chat.completions.parse.return_value = _mock_parsed(make_recommendations())
        generate_recommendations(make_analysis(), make_risk_profile(), make_macro())
        assert mock_client.beta.chat.completions.parse.call_args.kwargs["model"] == "gpt-4o"

    @patch("src.llm.recommendations.client")
    def test_uses_recommendations_system_prompt(self, mock_client):
        mock_client.beta.chat.completions.parse.return_value = _mock_parsed(make_recommendations())
        generate_recommendations(make_analysis(), make_risk_profile(), make_macro())
        messages = mock_client.beta.chat.completions.parse.call_args.kwargs["messages"]
        system = next(m for m in messages if m["role"] == "system")
        assert system["content"] == rec_prompts.SYSTEM


# --- write_letter ---

class TestWriteLetter:
    @patch("src.llm.writer.client")
    def test_returns_string(self, mock_client):
        mock_client.chat.completions.create.return_value = _mock_text("Prezado Albert...")
        result = write_letter(make_recommendations(), make_analysis())
        assert isinstance(result, str)
        assert len(result) > 0

    @patch("src.llm.writer.client")
    def test_uses_gpt4o(self, mock_client):
        mock_client.chat.completions.create.return_value = _mock_text("Prezado Albert...")
        write_letter(make_recommendations(), make_analysis())
        assert mock_client.chat.completions.create.call_args.kwargs["model"] == "gpt-4o"

    @patch("src.llm.writer.client")
    def test_uses_writer_system_prompt(self, mock_client):
        mock_client.chat.completions.create.return_value = _mock_text("Prezado Albert...")
        write_letter(make_recommendations(), make_analysis())
        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        system = next(m for m in messages if m["role"] == "system")
        assert system["content"] == writer_prompts.SYSTEM
