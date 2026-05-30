"""
Fetches market data from external APIs for a given report month.

Sources:
- Yahoo Finance: stock prices (current + previous month end) and Ibovespa
- CVM API: fund daily NAVs (cotas)
- BACEN API: CDI (série 12) and IPCA (série 433)
"""

import calendar
import contextlib
import csv
import io
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from io import StringIO
from pathlib import Path

import httpx
import pandas as pd
import yfinance as yf
from rapidfuzz import process as fuzz_process

# yfinance prints noisy HTTP errors and "possibly delisted" warnings to stderr.
# Silence them — our callers handle failures with their own clean messages.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("peewee").setLevel(logging.CRITICAL)

CVM_CADASTRO_URL = "https://dados.cvm.gov.br/dados/FI/CAD/DADOS/cad_fi.csv"
CVM_DIARIO_URL = "https://dados.cvm.gov.br/dados/FI/DOC/INF_DIARIO/DADOS/inf_diario_fi_{year}{month:02d}.csv"
BACEN_SERIES_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{series}/dados?formato=json&dataInicial={start}&dataFinal={end}"

CDI_SERIES = 12
IPCA_SERIES = 433


@dataclass
class StockMonthlyData:
    ticker: str
    end_of_month_price: float
    end_of_prev_month_price: float
    monthly_return_pct: float


@dataclass
class FundMonthlyData:
    name: str
    cnpj: str | None
    cvm_class: str | None          # CVM CLASSE field, e.g. "Ações", "Multimercado", "Renda Fixa"
    end_of_month_nav: float | None
    end_of_prev_month_nav: float | None
    monthly_return_pct: float | None  # None if fund not found in CVM


@dataclass
class BenchmarkData:
    cdi_monthly_pct: float
    ipca_monthly_pct: float
    ibovespa_monthly_pct: float


# --- Helpers ---

def _last_day_of_month(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _prev_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _date_range_str(year: int, month: int) -> tuple[str, str]:
    start = date(year, month, 1).strftime("%d/%m/%Y")
    end = _last_day_of_month(year, month).strftime("%d/%m/%Y")
    return start, end


# --- Stock prices (Yahoo Finance) ---

def _last_available_close(ticker_sa: str, target_date: date) -> float:
    """Returns the closing price on or before target_date."""
    start = (target_date - timedelta(days=7)).strftime("%Y-%m-%d")
    end = (target_date + timedelta(days=1)).strftime("%Y-%m-%d")
    with contextlib.redirect_stderr(io.StringIO()):
        hist = yf.Ticker(ticker_sa).history(start=start, end=end)
    if hist.empty:
        raise ValueError(f"No price data found for {ticker_sa} around {target_date}")
    return float(hist["Close"].iloc[-1])


def get_stock_monthly_data(ticker: str, year: int, month: int) -> StockMonthlyData:
    ticker_sa = f"{ticker}.SA"
    prev_year, prev_month = _prev_month(year, month)

    end_of_month = _last_day_of_month(year, month)
    end_of_prev_month = _last_day_of_month(prev_year, prev_month)

    current_price = _last_available_close(ticker_sa, end_of_month)
    prev_price = _last_available_close(ticker_sa, end_of_prev_month)
    monthly_return = (current_price - prev_price) / prev_price * 100

    return StockMonthlyData(
        ticker=ticker,
        end_of_month_price=current_price,
        end_of_prev_month_price=prev_price,
        monthly_return_pct=round(monthly_return, 2),
    )


# --- Fund NAVs (CVM) ---

@lru_cache(maxsize=1)
def _load_cvm_cad() -> pd.DataFrame:
    """Download and cache the CVM fund cadastre. At most one HTTP request per process."""
    response = httpx.get(CVM_CADASTRO_URL, timeout=60, follow_redirects=True)
    response.raise_for_status()
    df = pd.read_csv(
        StringIO(response.text), sep=";",
        dtype={"CNPJ_FUNDO": str}, encoding="latin-1", low_memory=False,
    )
    return df[df["SIT"] == "EM FUNCIONAMENTO NORMAL"].copy()


def _fuzzy_match_fund(fund_name: str, active: pd.DataFrame) -> pd.Series | None:
    """Returns the matched CVM row or None if no match above threshold."""
    names = active["DENOM_SOCIAL"].tolist()
    match = fuzz_process.extractOne(
        fund_name.upper(), [n.upper() for n in names], score_cutoff=75
    )
    if not match:
        return None
    return active[active["DENOM_SOCIAL"] == names[match[2]]].iloc[0]


def lookup_fund_cnpj(fund_name: str) -> str | None:
    """Fuzzy-matches fund name against CVM cadastre to get its CNPJ."""
    row = _fuzzy_match_fund(fund_name, _load_cvm_cad())
    return str(row["CNPJ_FUNDO"]) if row is not None else None


def lookup_fund_class(fund_name: str) -> str | None:
    """Returns the CVM CLASSE field for a fund (e.g. 'Ações', 'Multimercado', 'Renda Fixa').

    Returns None for funds not registered in the public CVM cadastre (e.g. Advisory funds).
    """
    row = _fuzzy_match_fund(fund_name, _load_cvm_cad())
    if row is None:
        return None
    val = row.get("CLASSE")
    return str(val) if pd.notna(val) else None


def _download_cvm_diario(year: int, month: int) -> pd.DataFrame:
    url = CVM_DIARIO_URL.format(year=year, month=month)
    response = httpx.get(url, timeout=60, follow_redirects=True)
    response.raise_for_status()
    df = pd.read_csv(StringIO(response.text), sep=";", dtype={"CNPJ_FUNDO": str})
    return df


def _get_last_nav(df: pd.DataFrame, cnpj: str) -> float | None:
    fund_df = df[df["CNPJ_FUNDO"] == cnpj].sort_values("DT_COMPTC")
    if fund_df.empty:
        return None
    return float(fund_df["VL_QUOTA"].iloc[-1])


def get_fund_monthly_data(fund_name: str, cnpj: str | None, cvm_class: str | None,
                          year: int, month: int) -> FundMonthlyData:
    if cnpj is None:
        return FundMonthlyData(name=fund_name, cnpj=None, cvm_class=cvm_class,
                               end_of_month_nav=None, end_of_prev_month_nav=None,
                               monthly_return_pct=None)

    prev_year, prev_month = _prev_month(year, month)

    df_current = _download_cvm_diario(year, month)
    df_prev = _download_cvm_diario(prev_year, prev_month)

    nav_current = _get_last_nav(df_current, cnpj)
    nav_prev = _get_last_nav(df_prev, cnpj)

    if nav_current is None or nav_prev is None:
        return FundMonthlyData(name=fund_name, cnpj=cnpj, cvm_class=cvm_class,
                               end_of_month_nav=nav_current,
                               end_of_prev_month_nav=nav_prev, monthly_return_pct=None)

    monthly_return = (nav_current - nav_prev) / nav_prev * 100
    return FundMonthlyData(
        name=fund_name, cnpj=cnpj, cvm_class=cvm_class,
        end_of_month_nav=nav_current, end_of_prev_month_nav=nav_prev,
        monthly_return_pct=round(monthly_return, 2),
    )


# --- CDI and IPCA (BACEN) ---

def get_cdi_monthly_pct(year: int, month: int) -> float:
    """Returns the compounded CDI for the month as a percentage (e.g. 0.89)."""
    start, end = _date_range_str(year, month)
    url = BACEN_SERIES_URL.format(series=CDI_SERIES, start=start, end=end)
    data = httpx.get(url, timeout=30).json()
    if not data:
        raise ValueError(f"No CDI data for {month}/{year}")
    # Daily rates are already in %, compound them
    compounded = 1.0
    for entry in data:
        compounded *= 1 + float(entry["valor"]) / 100
    return round((compounded - 1) * 100, 4)


def get_ipca_monthly_pct(year: int, month: int) -> float:
    """Returns the IPCA variation for the month as a percentage (e.g. 0.43)."""
    start, end = _date_range_str(year, month)
    url = BACEN_SERIES_URL.format(series=IPCA_SERIES, start=start, end=end)
    data = httpx.get(url, timeout=30).json()
    if not data:
        raise ValueError(f"No IPCA data for {month}/{year}")
    return float(data[-1]["valor"])


def get_cdb_monthly_return_pct(ipca_monthly_pct: float, spread_annual_pct: float) -> float:
    """
    Calculates CDB IPCA+ monthly return.
    Formula: (1 + IPCA_monthly) * (1 + spread_annual)^(1/12) - 1
    """
    ipca = ipca_monthly_pct / 100
    spread_monthly = (1 + spread_annual_pct / 100) ** (1 / 12) - 1
    monthly_return = (1 + ipca) * (1 + spread_monthly) - 1
    return round(monthly_return * 100, 4)


# --- Ibovespa (Yahoo Finance) ---

def get_ibovespa_monthly_pct(year: int, month: int) -> float:
    prev_year, prev_month = _prev_month(year, month)
    end_of_month = _last_day_of_month(year, month)
    end_of_prev_month = _last_day_of_month(prev_year, prev_month)

    current = _last_available_close("^BVSP", end_of_month)
    prev = _last_available_close("^BVSP", end_of_prev_month)

    return round((current - prev) / prev * 100, 2)


def get_benchmarks(year: int, month: int) -> BenchmarkData:
    return BenchmarkData(
        cdi_monthly_pct=get_cdi_monthly_pct(year, month),
        ipca_monthly_pct=get_ipca_monthly_pct(year, month),
        ibovespa_monthly_pct=get_ibovespa_monthly_pct(year, month),
    )


# --- Watchlist ---

def load_watchlist(csv_path: Path, year: int, month: int) -> list[dict]:
    """Load advisor watchlist CSV and enrich each ticker with live monthly return.

    CSV format (header required):
        ticker,thesis
        ITUB4,Banco sólido com dividendos consistentes

    The `thesis` column is optional — if omitted, thesis will be null.
    Tickers with no price data (delisted, etc.) are included with monthly_return_pct=null.
    """
    items: list[dict] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker = row["ticker"].strip()
            thesis = row.get("thesis", "").strip() or None
            try:
                data = get_stock_monthly_data(ticker, year, month)
                monthly_return = data.monthly_return_pct
            except Exception:
                monthly_return = None
            items.append({
                "ticker": ticker,
                "monthly_return_pct": monthly_return,
                "thesis": thesis,
            })
    return items
