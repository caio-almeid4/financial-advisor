from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.data.market import (
    BenchmarkData,
    FundMonthlyData,
    StockMonthlyData,
    _last_day_of_month,
    _prev_month,
    get_benchmarks,
    get_cdb_monthly_return_pct,
    get_cdi_monthly_pct,
    get_fund_monthly_data,
    get_ibovespa_monthly_pct,
    get_ipca_monthly_pct,
    get_stock_monthly_data,
    lookup_fund_cnpj,
)


# --- Helpers ---

class TestLastDayOfMonth:
    def test_regular_month(self):
        assert _last_day_of_month(2025, 4) == date(2025, 4, 30)

    def test_january(self):
        assert _last_day_of_month(2025, 1) == date(2025, 1, 31)

    def test_february_non_leap(self):
        assert _last_day_of_month(2025, 2) == date(2025, 2, 28)

    def test_february_leap(self):
        assert _last_day_of_month(2024, 2) == date(2024, 2, 29)


class TestPrevMonth:
    def test_mid_year(self):
        assert _prev_month(2025, 4) == (2025, 3)

    def test_january_wraps_to_december(self):
        assert _prev_month(2025, 1) == (2024, 12)


# --- CDB calculation (pure function, no mocking needed) ---

class TestCdbMonthlyReturn:
    def test_positive_ipca_and_spread(self):
        result = get_cdb_monthly_return_pct(ipca_monthly_pct=0.43, spread_annual_pct=5.45)
        # Expected: (1.0043) * (1.0545)^(1/12) - 1 ≈ 0.87%
        assert 0.7 < result < 1.1

    def test_zero_ipca(self):
        result = get_cdb_monthly_return_pct(ipca_monthly_pct=0.0, spread_annual_pct=5.45)
        # Pure spread: (1.0545)^(1/12) - 1 ≈ 0.443%
        assert 0.3 < result < 0.6

    def test_returns_float(self):
        assert isinstance(get_cdb_monthly_return_pct(0.43, 5.45), float)


# --- Stock data (mocked Yahoo Finance) ---

def _mock_yf_ticker(prices: list[float]):
    hist = pd.DataFrame({"Close": prices})
    ticker = MagicMock()
    ticker.history.return_value = hist
    return ticker


class TestGetStockMonthlyData:
    @patch("src.data.market.yf.Ticker")
    def test_returns_stock_monthly_data(self, mock_ticker_cls):
        mock_ticker_cls.return_value = _mock_yf_ticker([16.94])
        result = get_stock_monthly_data("LREN3", 2025, 4)
        assert isinstance(result, StockMonthlyData)
        assert result.ticker == "LREN3"

    @patch("src.data.market.yf.Ticker")
    def test_monthly_return_calculation(self, mock_ticker_cls):
        # First call → current month (price 16.94), second call → prev month (price 15.55)
        mock_ticker_cls.side_effect = [
            _mock_yf_ticker([16.94]),
            _mock_yf_ticker([15.55]),
        ]
        result = get_stock_monthly_data("LREN3", 2025, 4)
        expected_return = (16.94 - 15.55) / 15.55 * 100
        assert result.monthly_return_pct == pytest.approx(expected_return, rel=0.01)

    @patch("src.data.market.yf.Ticker")
    def test_uses_sa_suffix_for_brazilian_stocks(self, mock_ticker_cls):
        mock_ticker_cls.return_value = _mock_yf_ticker([10.0])
        get_stock_monthly_data("PETR4", 2025, 4)
        calls = [call[0][0] for call in mock_ticker_cls.call_args_list]
        assert all(t == "PETR4.SA" for t in calls)

    @patch("src.data.market.yf.Ticker")
    def test_empty_history_raises(self, mock_ticker_cls):
        ticker = MagicMock()
        ticker.history.return_value = pd.DataFrame({"Close": []})
        mock_ticker_cls.return_value = ticker
        with pytest.raises(ValueError, match="No price data"):
            get_stock_monthly_data("LREN3", 2025, 4)


# --- Fund CNPJ lookup (mocked HTTP) ---

def _mock_cadastro_csv():
    return (
        "CNPJ_FUNDO;DENOM_SOCIAL;SIT\n"
        "11.111.111/0001-11;RIZA LOTUS PLUS ADVISORY FIC FIRF REF DI CP;EM FUNCIONAMENTO NORMAL\n"
        "22.222.222/0001-22;BRAVE I FIC FIM CP;EM FUNCIONAMENTO NORMAL\n"
        "33.333.333/0001-33;FUNDO ENCERRADO;CANCELADA\n"
    )


class TestLookupFundCnpj:
    @patch("src.data.market.httpx.get")
    def test_finds_exact_match(self, mock_get):
        mock_get.return_value = MagicMock(text=_mock_cadastro_csv(), status_code=200)
        mock_get.return_value.raise_for_status = MagicMock()
        cnpj = lookup_fund_cnpj("Riza Lotus Plus Advisory FIC FIRF REF DI CP")
        assert cnpj == "11.111.111/0001-11"

    @patch("src.data.market.httpx.get")
    def test_ignores_cancelled_funds(self, mock_get):
        mock_get.return_value = MagicMock(text=_mock_cadastro_csv(), status_code=200)
        mock_get.return_value.raise_for_status = MagicMock()
        cnpj = lookup_fund_cnpj("Fundo Encerrado")
        assert cnpj is None

    @patch("src.data.market.httpx.get")
    def test_returns_none_for_no_match(self, mock_get):
        mock_get.return_value = MagicMock(text=_mock_cadastro_csv(), status_code=200)
        mock_get.return_value.raise_for_status = MagicMock()
        cnpj = lookup_fund_cnpj("Fundo Que Nao Existe XYZ 123")
        assert cnpj is None


# --- Fund monthly data (mocked HTTP) ---

def _mock_diario_csv(cnpj: str, nav_value: float):
    return (
        f"CNPJ_FUNDO;DT_COMPTC;VL_TOTAL;VL_QUOTA;VL_PATRIM_LIQ;CAPTC_DIA;RESG_DIA;NR_COTST\n"
        f"{cnpj};2025-04-30;1000000;{nav_value};1000000;0;0;100\n"
    )


class TestGetFundMonthlyData:
    @patch("src.data.market.httpx.get")
    def test_returns_none_monthly_return_when_cnpj_is_none(self, mock_get):
        result = get_fund_monthly_data("Some Fund", cnpj=None, cvm_class=None, year=2025, month=4)
        assert result.monthly_return_pct is None
        assert result.cnpj is None
        assert result.cvm_class is None
        mock_get.assert_not_called()

    @patch("src.data.market.httpx.get")
    def test_calculates_monthly_return(self, mock_get):
        cnpj = "11.111.111/0001-11"
        current_csv = _mock_diario_csv(cnpj, nav_value=10.50)
        prev_csv = _mock_diario_csv(cnpj, nav_value=10.00)

        responses = [
            MagicMock(text=current_csv, status_code=200, raise_for_status=MagicMock()),
            MagicMock(text=prev_csv, status_code=200, raise_for_status=MagicMock()),
        ]
        mock_get.side_effect = responses

        result = get_fund_monthly_data("Some Fund", cnpj=cnpj, cvm_class="Multimercado", year=2025, month=4)
        expected = (10.50 - 10.00) / 10.00 * 100
        assert result.monthly_return_pct == pytest.approx(expected, rel=0.01)


# --- BACEN API (mocked HTTP) ---

class TestGetCdiMonthly:
    @patch("src.data.market.httpx.get")
    def test_compounds_daily_rates(self, mock_get):
        # Simulate 2 days of CDI at 0.05% each
        mock_get.return_value = MagicMock()
        mock_get.return_value.json.return_value = [
            {"data": "01/04/2025", "valor": "0.05"},
            {"data": "02/04/2025", "valor": "0.05"},
        ]
        result = get_cdi_monthly_pct(2025, 4)
        expected = ((1.0005) ** 2 - 1) * 100
        assert result == pytest.approx(expected, rel=0.01)

    @patch("src.data.market.httpx.get")
    def test_raises_on_empty_data(self, mock_get):
        mock_get.return_value = MagicMock()
        mock_get.return_value.json.return_value = []
        with pytest.raises(ValueError, match="No CDI data"):
            get_cdi_monthly_pct(2025, 4)


class TestGetIpcaMonthly:
    @patch("src.data.market.httpx.get")
    def test_returns_last_entry_value(self, mock_get):
        mock_get.return_value = MagicMock()
        mock_get.return_value.json.return_value = [{"data": "30/04/2025", "valor": "0.43"}]
        result = get_ipca_monthly_pct(2025, 4)
        assert result == 0.43

    @patch("src.data.market.httpx.get")
    def test_raises_on_empty_data(self, mock_get):
        mock_get.return_value = MagicMock()
        mock_get.return_value.json.return_value = []
        with pytest.raises(ValueError, match="No IPCA data"):
            get_ipca_monthly_pct(2025, 4)


# --- Integration tests ---

@pytest.mark.integration
class TestMarketIntegration:
    def test_get_cdi_monthly_april_2025(self):
        result = get_cdi_monthly_pct(2025, 4)
        assert 0.5 < result < 2.0

    def test_get_ipca_monthly_april_2025(self):
        result = get_ipca_monthly_pct(2025, 4)
        assert -1.0 < result < 3.0

    def test_get_ibovespa_monthly_april_2025(self):
        result = get_ibovespa_monthly_pct(2025, 4)
        assert -20.0 < result < 20.0

    def test_get_stock_lren3_april_2025(self):
        result = get_stock_monthly_data("LREN3", 2025, 4)
        assert result.ticker == "LREN3"
        assert result.end_of_month_price > 0
        assert result.end_of_prev_month_price > 0

    def test_advisory_fund_not_in_cvm(self):
        # XP Advisory funds are exclusive vehicles not registered in the public CVM database.
        # This is expected — in production, fund NAVs would come from XP's internal API.
        cnpj = lookup_fund_cnpj("Riza Lotus Plus Advisory FIC FIRF REF DI CP")
        assert cnpj is None
