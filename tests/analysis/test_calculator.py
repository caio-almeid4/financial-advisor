from pathlib import Path
from unittest.mock import patch

import pytest

from src.analysis.calculator import (
    _allocation_status,
    _current_allocation,
    _investable_balance,
    _liquidity_tier,
    _weighted_portfolio_return,
    analyze_portfolio,
    classify_fund,

)
from src.analysis.models import AssetReturn, AllocationStatus
from src.ingestion.models import (
    FixedIncome,
    Fund,
    Portfolio,
    RiskProfile,
    Stock,
    TargetAllocation,
)

DATA_DIR = Path(__file__).parent.parent.parent


# --- classify_fund ---

class TestClassifyFund:
    def test_fia_returns_fundos_acoes(self):
        assert classify_fund("STK Long Biased FIC FIA") == "fundos_acoes"

    def test_fim_returns_fundos_multimercado(self):
        assert classify_fund("Brave I FIC FIM CP") == "fundos_multimercado"

    def test_firf_returns_renda_fixa(self):
        assert classify_fund("Riza Lotus Plus Advisory FIC FIRF REF DI CP") == "renda_fixa"

    def test_unknown_defaults_to_multimercado(self):
        assert classify_fund("Some Unknown Fund") == "fundos_multimercado"

    def test_case_insensitive(self):
        assert classify_fund("fundo fia") == "fundos_acoes"

    def test_cvm_class_takes_priority_over_name(self):
        # Name says FIA but CVM says Renda Fixa — trust CVM
        assert classify_fund("Fundo FIA Qualquer", cvm_class="Renda Fixa") == "renda_fixa"

    def test_cvm_class_acoes(self):
        assert classify_fund("Qualquer Nome", cvm_class="Ações Livre") == "fundos_acoes"

    def test_cvm_class_multimercado(self):
        assert classify_fund("Qualquer Nome", cvm_class="Multimercados Macro") == "fundos_multimercado"

    def test_cvm_class_referenciado(self):
        assert classify_fund("Qualquer Nome", cvm_class="Referenciado DI") == "renda_fixa"

    def test_falls_back_to_name_when_cvm_class_is_none(self):
        assert classify_fund("Advisory FIC FIA", cvm_class=None) == "fundos_acoes"


# --- _current_allocation ---

def make_portfolio_for_allocation() -> Portfolio:
    return Portfolio(
        client_name="Test", account="000", reference_date="01/04/2025",
        total_invested=100000,
        available_balance=0.0,
        total_patrimony=100000.0,
        advisor_name="Test Advisor",
        advisor_code="T0000",
        stocks=[
            Stock(ticker="LREN3", position_value=20000, allocation_pct=20.0,
                  return_since_inception_pct=-10.0, investment_date="01/01/2021",
                  average_price=10.0, current_price=8.0, quantity=2500),
        ],
        funds=[
            Fund(name="Brave I FIC FIM CP", position_value=50000, allocation_pct=50.0,
                 return_since_inception_pct=10.0, investment_date="01/01/2021",
                 invested_amount=45000, current_value=50000),
            Fund(name="STK Long Biased FIC FIA", position_value=20000, allocation_pct=20.0,
                 return_since_inception_pct=-5.0, investment_date="01/01/2022",
                 invested_amount=22000, current_value=20000),
        ],
        fixed_income=[
            FixedIncome(type="CDB", issuer="Banco C6", position_value=10000,
                        allocation_pct=10.0, invested_amount=8000, rate="IPCA+5.45%",
                        investment_date="01/01/2023", maturity_date="01/01/2025"),
        ],
    )


class TestCurrentAllocation:
    def test_sums_correctly(self):
        portfolio = make_portfolio_for_allocation()
        alloc = _current_allocation(portfolio)
        total = sum(alloc.values())
        assert total == pytest.approx(1.0, abs=0.01)

    def test_stocks_in_acoes(self):
        alloc = _current_allocation(make_portfolio_for_allocation())
        assert alloc["acoes"] == pytest.approx(0.20, abs=0.01)

    def test_fim_fund_in_multimercado(self):
        alloc = _current_allocation(make_portfolio_for_allocation())
        assert alloc["fundos_multimercado"] == pytest.approx(0.50, abs=0.01)

    def test_fia_fund_in_fundos_acoes(self):
        alloc = _current_allocation(make_portfolio_for_allocation())
        assert alloc["fundos_acoes"] == pytest.approx(0.20, abs=0.01)

    def test_cdb_in_renda_fixa(self):
        alloc = _current_allocation(make_portfolio_for_allocation())
        assert alloc["renda_fixa"] == pytest.approx(0.10, abs=0.01)


# --- _allocation_status ---

def make_risk_profile() -> RiskProfile:
    return RiskProfile(
        client_name="Test", classification="Moderado",
        description="", compatible_products=[],
        target_allocation=TargetAllocation(
            acoes_pct=0.20, renda_fixa_pct=0.30,
            fundos_multimercado_pct=0.35, fundos_acoes_pct=0.15,
        ),
    )


class TestAllocationStatus:
    def test_returns_one_status_per_class(self):
        current = {"acoes": 0.20, "renda_fixa": 0.10, "fundos_multimercado": 0.50, "fundos_acoes": 0.20}
        status = _allocation_status(current, make_risk_profile())
        assert len(status) == 4

    def test_gap_is_current_minus_target(self):
        current = {"acoes": 0.05, "renda_fixa": 0.30, "fundos_multimercado": 0.35, "fundos_acoes": 0.30}
        status = _allocation_status(current, make_risk_profile())
        acoes_status = next(s for s in status if s.asset_class == "acoes")
        assert acoes_status.gap_pct == pytest.approx(0.05 - 0.20, abs=0.001)

    def test_overweight_has_positive_gap(self):
        current = {"acoes": 0.40, "renda_fixa": 0.20, "fundos_multimercado": 0.25, "fundos_acoes": 0.15}
        status = _allocation_status(current, make_risk_profile())
        acoes_status = next(s for s in status if s.asset_class == "acoes")
        assert acoes_status.gap_pct > 0


# --- _weighted_portfolio_return ---

def make_asset(monthly_return_pct, allocation_pct) -> AssetReturn:
    return AssetReturn(
        name="X", asset_class="acoes",
        allocation_pct=allocation_pct,
        monthly_return_pct=monthly_return_pct,
        return_since_inception_pct=0.0,
        monthly_vs_benchmark=None,
        benchmark="CDI",
        investment_date="01/01/2024",
    )


class TestWeightedPortfolioReturn:
    def test_simple_weighted_average(self):
        assets = [make_asset(10.0, 50.0), make_asset(20.0, 50.0)]
        result = _weighted_portfolio_return(assets)
        assert result == pytest.approx(15.0, rel=0.01)

    def test_computes_with_partial_coverage(self):
        # Should compute from available data regardless of coverage %
        assets = [make_asset(10.0, 40.0), make_asset(None, 60.0)]
        result = _weighted_portfolio_return(assets)
        assert result == pytest.approx(10.0, rel=0.01)

    def test_computes_when_minority_has_data(self):
        assets = [make_asset(10.0, 20.0), make_asset(None, 80.0)]
        result = _weighted_portfolio_return(assets)
        assert result is not None

    def test_all_none_returns_none(self):
        assets = [make_asset(None, 50.0), make_asset(None, 50.0)]
        assert _weighted_portfolio_return(assets) is None


# --- load_watchlist ---

class TestRateParsing:
    """Exercises the spread extraction from fi.rate inside analyze_portfolio."""

    def _spread_from(self, rate: str) -> float:
        from src.ingestion.models import FixedIncome, Portfolio, Stock, Fund
        from src.analysis.models import PortfolioAnalysis
        from src.data.market import BenchmarkData, StockMonthlyData, FundMonthlyData
        fi = FixedIncome(type="CDB", issuer="Banco", position_value=1000,
                         allocation_pct=100.0, invested_amount=900,
                         rate=rate, investment_date="01/01/2023", maturity_date="01/01/2026")
        portfolio = Portfolio(client_name="Test", account="0", reference_date="31/05/2025",
                              total_invested=1000, available_balance=0.0, total_patrimony=1000.0,
                              advisor_name="Test Advisor", advisor_code="T0000",
                              stocks=[], funds=[], fixed_income=[fi])
        from src.ingestion.models import RiskProfile, TargetAllocation
        risk = RiskProfile(client_name="Test", classification="Moderado", description="",
                           compatible_products=[],
                           target_allocation=TargetAllocation(acoes_pct=0.25, renda_fixa_pct=0.25,
                                                               fundos_multimercado_pct=0.25, fundos_acoes_pct=0.25))
        benchmarks = BenchmarkData(cdi_monthly_pct=1.0, ipca_monthly_pct=0.3, ibovespa_monthly_pct=1.5)
        result = analyze_portfolio(portfolio, risk, {}, {}, benchmarks, 0.3, 2025, 5)
        return result.assets[0].monthly_return_pct

    def test_dot_decimal(self):
        r = self._spread_from("IPCA+5.45%")
        assert r is not None and r > 0

    def test_comma_decimal_br(self):
        r = self._spread_from("IPC-A +5,45%")
        assert r is not None and r > 0

    def test_dot_and_comma_give_same_result(self):
        assert self._spread_from("IPCA+5.45%") == pytest.approx(
            self._spread_from("IPC-A +5,45%"), rel=0.001
        )


# --- _liquidity_tier ---

class TestLiquidityTier:
    def test_aggressive_above_40pct_equity(self):
        ta = TargetAllocation(acoes_pct=0.30, renda_fixa_pct=0.20,
                              fundos_multimercado_pct=0.30, fundos_acoes_pct=0.20)
        assert _liquidity_tier(ta) == 0.03

    def test_moderate_15_to_40pct_equity(self):
        ta = TargetAllocation(acoes_pct=0.20, renda_fixa_pct=0.45,
                              fundos_multimercado_pct=0.20, fundos_acoes_pct=0.15)
        assert _liquidity_tier(ta) == 0.05

    def test_conservative_below_15pct_equity(self):
        ta = TargetAllocation(acoes_pct=0.05, renda_fixa_pct=0.80,
                              fundos_multimercado_pct=0.10, fundos_acoes_pct=0.05)
        assert _liquidity_tier(ta) == 0.10


# --- _investable_balance ---

class TestInvestableBalance:
    def _make_portfolio(self, total_invested: float, available: float) -> Portfolio:
        return Portfolio(
            client_name="T", account="0", reference_date="01/04/2025",
            total_invested=total_invested,
            available_balance=available,
            total_patrimony=total_invested + available,
            advisor_name="A", advisor_code="X",
            stocks=[], funds=[], fixed_income=[],
        )

    def test_zero_available_returns_zero(self):
        p = self._make_portfolio(100000.0, 0.0)
        assert _investable_balance(p, 0.05) == 0.0

    def test_surplus_above_buffer(self):
        # total = 312186 + 74672 = 386858; buffer = 0.05 * 386858 ≈ 19342.9
        # investable = 74672 - 19342.9 ≈ 55329.1
        p = self._make_portfolio(312186.0, 74672.0)
        result = _investable_balance(p, 0.05)
        expected = 74672.0 - (312186.0 + 74672.0) * 0.05
        assert result == pytest.approx(expected, abs=0.1)

    def test_never_negative(self):
        # available_balance smaller than buffer → returns 0, not negative
        p = self._make_portfolio(1_000_000.0, 1000.0)
        assert _investable_balance(p, 0.10) == 0.0


