import pytest
from pydantic import ValidationError

from src.ingestion.models import (
    FixedIncome,
    Fund,
    MacroAnalysis,
    MacroProjections,
    Portfolio,
    RiskProfile,
    Stock,
    TargetAllocation,
)


def make_stock(**overrides):
    defaults = dict(
        ticker="LREN3",
        position_value=27812.04,
        allocation_pct=8.91,
        return_since_inception_pct=-41.7,
        investment_date="22/04/2021",
        average_price=29.05,
        current_price=16.94,
        quantity=1642,
    )
    return Stock(**{**defaults, **overrides})


def make_fund(**overrides):
    defaults = dict(
        name="Riza Lotus Plus Advisory FIC FIRF REF DI CP",
        position_value=96178.73,
        allocation_pct=30.81,
        return_since_inception_pct=15.51,
        investment_date="22/04/2021",
        invested_amount=83267.36,
        current_value=95254.02,
    )
    return Fund(**{**defaults, **overrides})


def make_fixed_income(**overrides):
    defaults = dict(
        type="CDB",
        issuer="Banco C6",
        position_value=40478.75,
        allocation_pct=12.97,
        invested_amount=30000.0,
        rate="IPCA+5.45%",
        investment_date="09/11/2023",
        maturity_date="05/09/2024",
    )
    return FixedIncome(**{**defaults, **overrides})


def make_portfolio(**overrides):
    defaults = dict(
        client_name="Albert da Silva",
        account="792854",
        reference_date="07/05/2025",
        total_invested=312186.20,
        available_balance=74672.62,
        total_patrimony=386858.82,
        advisor_name="Antonio Bicudo",
        advisor_code="A7699",
        stocks=[make_stock()],
        funds=[make_fund()],
        fixed_income=[make_fixed_income()],
    )
    return Portfolio(**{**defaults, **overrides})


def make_target_allocation(**overrides):
    defaults = dict(acoes_pct=0.20, renda_fixa_pct=0.45, fundos_multimercado_pct=0.20, fundos_acoes_pct=0.15)
    return TargetAllocation(**{**defaults, **overrides})


# --- Stock ---

class TestStock:
    def test_valid(self):
        s = make_stock()
        assert s.ticker == "LREN3"
        assert s.quantity == 1642

    def test_negative_return_is_valid(self):
        s = make_stock(return_since_inception_pct=-74.58)
        assert s.return_since_inception_pct == -74.58

    def test_missing_field_raises(self):
        with pytest.raises(ValidationError):
            Stock(ticker="LREN3")  # missing required fields


# --- Fund ---

class TestFund:
    def test_valid(self):
        f = make_fund()
        assert f.position_value == 96178.73

    def test_current_value_can_be_below_invested(self):
        f = make_fund(invested_amount=14250.0, current_value=12522.05)
        assert f.current_value < f.invested_amount


# --- TargetAllocation ---

class TestTargetAllocation:
    def test_valid_sums_to_one(self):
        t = make_target_allocation()
        assert abs(t.acoes_pct + t.renda_fixa_pct + t.fundos_multimercado_pct + t.fundos_acoes_pct - 1.0) < 0.01

    def test_does_not_sum_to_one_raises(self):
        with pytest.raises(ValidationError, match="sum to 1.0"):
            TargetAllocation(acoes_pct=0.50, renda_fixa_pct=0.50, fundos_multimercado_pct=0.50, fundos_acoes_pct=0.50)

    def test_tolerance_accepted(self):
        # Small floating point drift (within 0.01) should be accepted
        t = TargetAllocation(acoes_pct=0.20, renda_fixa_pct=0.451, fundos_multimercado_pct=0.20, fundos_acoes_pct=0.15)
        assert t is not None


# --- Portfolio ---

class TestPortfolio:
    def test_valid(self):
        p = make_portfolio()
        assert p.client_name == "Albert da Silva"
        assert len(p.stocks) == 1
        assert len(p.funds) == 1
        assert len(p.fixed_income) == 1

    def test_empty_asset_lists_valid(self):
        p = make_portfolio(stocks=[], funds=[], fixed_income=[])
        assert p.total_invested == 312186.20


# --- MacroProjections ---

class TestMacroProjections:
    def test_valid(self):
        m = MacroProjections(
            ipca_2025=6.1,
            ipca_2026=4.5,
            selic_terminal=15.5,
            gdp_growth_2025=2.0,
            usd_brl_end_2025=6.20,
        )
        assert m.selic_terminal == 15.5


# --- MacroAnalysis ---

class TestMacroAnalysis:
    def test_valid(self):
        m = MacroAnalysis(
            date="2025-02-06",
            title="Brasil Macro Mensal",
            key_points=["Selic em alta", "IPCA pressionado"],
            projections=MacroProjections(
                ipca_2025=6.1, ipca_2026=4.5, selic_terminal=15.5,
                gdp_growth_2025=2.0, usd_brl_end_2025=6.20,
            ),
            editorial_summary="Cenário de juros altos por tempo prolongado.",
        )
        assert len(m.key_points) == 2
