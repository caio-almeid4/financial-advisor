from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.ingestion.models import (
    MacroAnalysis,
    MacroProjections,
    Portfolio,
    RiskProfile,
    Stock,
    Fund,
    FixedIncome,
    TargetAllocation,
)
from src.ingestion.parser import parse_macro_analysis, parse_portfolio, parse_risk_profile
from src.prompts import macro_analysis as macro_prompts
from src.prompts import portfolio as portfolio_prompts
from src.prompts import risk_profile as risk_prompts

DATA_DIR = Path(__file__).parent.parent.parent


def _mock_parsed_response(parsed_object):
    """Build the mock structure that mirrors client.beta.chat.completions.parse()."""
    message = MagicMock()
    message.parsed = parsed_object
    choice = MagicMock()
    choice.message = message
    completion = MagicMock()
    completion.choices = [choice]
    return completion


SAMPLE_PORTFOLIO = Portfolio(
    client_name="Albert da Silva",
    account="792854",
    reference_date="07/05/2025",
    total_invested=312186.20,
    available_balance=74672.62,
    total_patrimony=386858.82,
    advisor_name="Antonio Bicudo",
    advisor_code="A7699",
    stocks=[
        Stock(
            ticker="LREN3", position_value=27812.04, allocation_pct=8.91,
            return_since_inception_pct=-41.7, investment_date="22/04/2021",
            average_price=29.05, current_price=16.94, quantity=1642,
        )
    ],
    funds=[
        Fund(
            name="Riza Lotus Plus Advisory FIC FIRF REF DI CP",
            position_value=96178.73, allocation_pct=30.81,
            return_since_inception_pct=15.51, investment_date="22/04/2021",
            invested_amount=83267.36, current_value=95254.02,
        )
    ],
    fixed_income=[
        FixedIncome(
            type="CDB", issuer="Banco C6", position_value=40478.75,
            allocation_pct=12.97, invested_amount=30000.0, rate="IPCA+5.45%",
            investment_date="09/11/2023", maturity_date="05/09/2024",
        )
    ],
)

SAMPLE_RISK_PROFILE = RiskProfile(
    client_name="Albert",
    classification="Moderado",
    description="Perfil intermediário entre conservador e arrojado.",
    compatible_products=["Ações com dividendos", "Renda fixa BB+"],
    target_allocation=TargetAllocation(
        acoes_pct=0.20, renda_fixa_pct=0.45,
        fundos_multimercado_pct=0.20, fundos_acoes_pct=0.15,
    ),
)

SAMPLE_MACRO = MacroAnalysis(
    date="2025-02-06",
    title="Brasil Macro Mensal",
    key_points=["Selic em 15.5%", "IPCA projetado em 6.1% para 2025"],
    projections=MacroProjections(
        ipca_2025=6.1, ipca_2026=4.5, selic_terminal=15.5,
        gdp_growth_2025=2.0, usd_brl_end_2025=6.20,
    ),
    editorial_summary="Cenário de juros altos e inflação persistente.",
)


class TestParsePortfolio:
    @patch("src.ingestion.parser.client")
    def test_returns_portfolio_object(self, mock_client):
        mock_client.beta.chat.completions.parse.return_value = _mock_parsed_response(SAMPLE_PORTFOLIO)
        result = parse_portfolio(DATA_DIR / "XP - Albert's portfolio.txt")
        assert isinstance(result, Portfolio)
        assert result.client_name == "Albert da Silva"

    @patch("src.ingestion.parser.client")
    def test_uses_gpt4o_model(self, mock_client):
        mock_client.beta.chat.completions.parse.return_value = _mock_parsed_response(SAMPLE_PORTFOLIO)
        parse_portfolio(DATA_DIR / "XP - Albert's portfolio.txt")
        call_kwargs = mock_client.beta.chat.completions.parse.call_args
        assert call_kwargs.kwargs["model"] == "gpt-4o-mini"

    @patch("src.ingestion.parser.client")
    def test_uses_portfolio_system_prompt(self, mock_client):
        mock_client.beta.chat.completions.parse.return_value = _mock_parsed_response(SAMPLE_PORTFOLIO)
        parse_portfolio(DATA_DIR / "XP - Albert's portfolio.txt")
        messages = mock_client.beta.chat.completions.parse.call_args.kwargs["messages"]
        system_message = next(m for m in messages if m["role"] == "system")
        assert system_message["content"] == portfolio_prompts.SYSTEM

    @patch("src.ingestion.parser.client")
    def test_passes_file_content_as_user_message(self, mock_client):
        mock_client.beta.chat.completions.parse.return_value = _mock_parsed_response(SAMPLE_PORTFOLIO)
        txt_path = DATA_DIR / "XP - Albert's portfolio.txt"
        parse_portfolio(txt_path)
        messages = mock_client.beta.chat.completions.parse.call_args.kwargs["messages"]
        user_message = next(m for m in messages if m["role"] == "user")
        assert "Albert da Silva" in user_message["content"]


class TestParseRiskProfile:
    @patch("src.ingestion.parser.client")
    def test_returns_risk_profile_object(self, mock_client):
        mock_client.beta.chat.completions.parse.return_value = _mock_parsed_response(SAMPLE_RISK_PROFILE)
        result = parse_risk_profile(DATA_DIR / "XP - Albert's risk profile.txt")
        assert isinstance(result, RiskProfile)
        assert result.classification == "Moderado"

    @patch("src.ingestion.parser.client")
    def test_uses_risk_profile_system_prompt(self, mock_client):
        mock_client.beta.chat.completions.parse.return_value = _mock_parsed_response(SAMPLE_RISK_PROFILE)
        parse_risk_profile(DATA_DIR / "XP - Albert's risk profile.txt")
        messages = mock_client.beta.chat.completions.parse.call_args.kwargs["messages"]
        system_message = next(m for m in messages if m["role"] == "system")
        assert system_message["content"] == risk_prompts.SYSTEM


class TestParseMacroAnalysis:
    @patch("src.ingestion.parser.client")
    def test_returns_macro_analysis_object(self, mock_client):
        mock_client.beta.chat.completions.parse.return_value = _mock_parsed_response(SAMPLE_MACRO)
        result = parse_macro_analysis(DATA_DIR / "XP - Macro analysis.txt")
        assert isinstance(result, MacroAnalysis)
        assert result.projections.selic_terminal == 15.5

    @patch("src.ingestion.parser.client")
    def test_uses_macro_system_prompt(self, mock_client):
        mock_client.beta.chat.completions.parse.return_value = _mock_parsed_response(SAMPLE_MACRO)
        parse_macro_analysis(DATA_DIR / "XP - Macro analysis.txt")
        messages = mock_client.beta.chat.completions.parse.call_args.kwargs["messages"]
        system_message = next(m for m in messages if m["role"] == "system")
        assert system_message["content"] == macro_prompts.SYSTEM


# --- Integration tests (call real OpenAI API) ---

@pytest.mark.integration
class TestIntegration:
    def test_parse_portfolio_real(self):
        p = parse_portfolio(DATA_DIR / "XP - Albert's portfolio.txt")
        assert {s.ticker for s in p.stocks} == {"LREN3", "MRFG3", "ARZZ3", "HAPV3"}
        assert len(p.funds) == 7
        assert p.total_invested == pytest.approx(386858.82, rel=0.01)

    def test_parse_risk_profile_real(self):
        rp = parse_risk_profile(DATA_DIR / "XP - Albert's risk profile.txt")
        assert rp.classification == "Moderado"
        total = sum([
            rp.target_allocation.acoes_pct,
            rp.target_allocation.renda_fixa_pct,
            rp.target_allocation.fundos_multimercado_pct,
            rp.target_allocation.fundos_acoes_pct,
        ])
        assert total == pytest.approx(1.0, abs=0.01)

    def test_parse_macro_real(self):
        m = parse_macro_analysis(DATA_DIR / "XP - Macro analysis.txt")
        assert m.projections.ipca_2025 == pytest.approx(6.1, rel=0.05)
        assert m.projections.selic_terminal == pytest.approx(15.5, rel=0.05)
        assert len(m.key_points) >= 5
