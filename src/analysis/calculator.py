import calendar

from src.analysis.flags import generate_flags
from src.analysis.models import AllocationStatus, AssetReturn, PortfolioAnalysis
from src.data.market import BenchmarkData, FundMonthlyData, StockMonthlyData, get_cdb_monthly_return_pct
from src.ingestion.models import Fund, Portfolio, RiskProfile, TargetAllocation

MONTH_NAMES_PT = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril",
    5: "maio", 6: "junho", 7: "julho", 8: "agosto",
    9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro",
}


# Maps CVM CLASSE prefixes to internal asset classes.
# Checked in order — first prefix match wins.
_CVM_CLASS_MAP: list[tuple[str, str]] = [
    ("Ações",        "fundos_acoes"),
    ("FII",          "fundos_acoes"),
    ("FIP",          "fundos_acoes"),       # private equity — equity-like
    ("Renda Fixa",   "renda_fixa"),
    ("Referenciado", "renda_fixa"),
    ("Curto Prazo",  "renda_fixa"),
    ("Dívida Externa", "renda_fixa"),
    ("FIDC",         "renda_fixa"),
    ("Multimercado", "fundos_multimercado"),
    ("Cambial",      "fundos_multimercado"),
]


_EQUITY_CLASSES = frozenset({"acoes", "fundos_acoes"})


def _benchmark_for_class(asset_class: str) -> str:
    return "Ibovespa" if asset_class in _EQUITY_CLASSES else "CDI"


def classify_fund(fund_name: str, cvm_class: str | None = None) -> str:
    """Returns the internal asset class for a fund.

    Priority:
    1. CVM CLASSE field (source of truth when fund is in public cadastre).
    2. Name-based inference (fallback for Advisory funds not in CVM).
    """
    if cvm_class:
        for prefix, asset_class in _CVM_CLASS_MAP:
            if cvm_class.startswith(prefix):
                return asset_class

    # Name-based fallback (Advisory funds and others absent from CVM)
    name = fund_name.upper()
    if "FIA" in name or "FII" in name:
        return "fundos_acoes"
    if name.endswith("11"):                # ETF B3 ticker convention
        return "fundos_acoes"
    if "FIRF" in name or "FIDC" in name or "FI RF" in name or "RENDA FIXA" in name:
        return "renda_fixa"
    return "fundos_multimercado"           # FIM and unknowns


def _current_allocation(portfolio: Portfolio) -> dict[str, float]:
    """Computes actual allocation % by asset class from the portfolio."""
    alloc: dict[str, float] = {
        "acoes": 0.0,
        "fundos_multimercado": 0.0,
        "fundos_acoes": 0.0,
        "renda_fixa": 0.0,
    }
    for stock in portfolio.stocks:
        alloc["acoes"] += stock.allocation_pct
    for fund in portfolio.funds:
        alloc[classify_fund(fund.name)] += fund.allocation_pct
    for fi in portfolio.fixed_income:
        alloc["renda_fixa"] += fi.allocation_pct
    return {k: round(v / 100, 4) for k, v in alloc.items()}  # convert % to fraction


def _allocation_status(current: dict[str, float], target: RiskProfile) -> list[AllocationStatus]:
    target_map = {
        "acoes": target.target_allocation.acoes_pct,
        "renda_fixa": target.target_allocation.renda_fixa_pct,
        "fundos_multimercado": target.target_allocation.fundos_multimercado_pct,
        "fundos_acoes": target.target_allocation.fundos_acoes_pct,
    }
    return [
        AllocationStatus(
            asset_class=cls,
            current_pct=round(current.get(cls, 0.0), 4),
            target_pct=target_map[cls],
            gap_pct=round(current.get(cls, 0.0) - target_map[cls], 4),
        )
        for cls in target_map
    ]


def _weighted_portfolio_return(assets: list[AssetReturn]) -> float | None:
    """Weighted average monthly return of assets that have monthly data available.

    Returns None only when zero assets have monthly data. In production all fund
    NAVs come from XP internal APIs, so coverage is always 100%.
    """
    weighted_sum = 0.0
    covered_weight = 0.0
    for asset in assets:
        if asset.monthly_return_pct is not None:
            weighted_sum += asset.monthly_return_pct * asset.allocation_pct
            covered_weight += asset.allocation_pct
    if covered_weight == 0.0:
        return None
    return round(weighted_sum / covered_weight, 4)


def _liquidity_tier(target_alloc: TargetAllocation) -> float:
    """Derives liquidity buffer % from equity weight in target allocation.

    Uses the target allocation data (not the profile name string) so the logic
    works for any profile name without hardcoding known classification labels.
    """
    equity_pct = target_alloc.acoes_pct + target_alloc.fundos_acoes_pct
    if equity_pct > 0.40:
        return 0.03   # aggressive
    if equity_pct >= 0.15:
        return 0.05   # moderate
    return 0.10       # conservative


def _investable_balance(portfolio: Portfolio, buffer_pct: float) -> float:
    """Cash available to invest after preserving a liquidity buffer.

    buffer = total_patrimony * buffer_pct
    investable = max(0, available_balance - buffer)
    """
    total = portfolio.total_invested + portfolio.available_balance
    return round(max(0.0, portfolio.available_balance - total * buffer_pct), 2)


def analyze_portfolio(
    portfolio: Portfolio,
    risk_profile: RiskProfile,
    stock_data: dict[str, StockMonthlyData],
    fund_data: dict[str, FundMonthlyData],
    benchmarks: BenchmarkData,
    ipca_monthly_pct: float,
    year: int,
    month: int,
) -> PortfolioAnalysis:

    cdi = benchmarks.cdi_monthly_pct

    # Build asset returns
    assets: list[AssetReturn] = []

    ibov = benchmarks.ibovespa_monthly_pct

    for stock in portfolio.stocks:
        market = stock_data.get(stock.ticker)
        monthly = market.monthly_return_pct if market else None
        assets.append(AssetReturn(
            name=stock.ticker,
            asset_class="acoes",
            allocation_pct=stock.allocation_pct,
            monthly_return_pct=monthly,
            return_since_inception_pct=stock.return_since_inception_pct,
            monthly_vs_benchmark=round(monthly - ibov, 4) if monthly is not None else None,
            benchmark="Ibovespa",
            investment_date=stock.investment_date,
        ))

    for fund in portfolio.funds:
        market = fund_data.get(fund.name)
        monthly = market.monthly_return_pct if market else None
        cvm_class = market.cvm_class if market else None
        asset_class = classify_fund(fund.name, cvm_class)
        benchmark = _benchmark_for_class(asset_class)
        bval = ibov if benchmark == "Ibovespa" else cdi
        assets.append(AssetReturn(
            name=fund.name,
            asset_class=asset_class,
            allocation_pct=fund.allocation_pct,
            monthly_return_pct=monthly,
            return_since_inception_pct=fund.return_since_inception_pct,
            monthly_vs_benchmark=round(monthly - bval, 4) if monthly is not None else None,
            benchmark=benchmark,
            investment_date=fund.investment_date,
        ))

    for fi in portfolio.fixed_income:
        spread = float(
            fi.rate.upper()
            .replace("IPC-A +", "").replace("IPCA +", "").replace("IPCA+", "")
            .replace("%", "")
            .replace(",", ".")   # handle BR decimal separator (e.g. "5,45" → "5.45")
            .strip()
        )
        monthly = get_cdb_monthly_return_pct(ipca_monthly_pct, spread)
        assets.append(AssetReturn(
            name=fi.issuer,
            asset_class="renda_fixa",
            allocation_pct=fi.allocation_pct,
            monthly_return_pct=monthly,
            return_since_inception_pct=round(
                (fi.position_value - fi.invested_amount) / fi.invested_amount * 100, 2
            ),
            monthly_vs_benchmark=round(monthly - cdi, 4),
            benchmark="CDI",
            investment_date=fi.investment_date,
        ))

    # Allocation analysis
    current_alloc = _current_allocation(portfolio)
    allocation_status = _allocation_status(current_alloc, risk_profile)

    # Liquidity buffer
    buffer_pct = _liquidity_tier(risk_profile.target_allocation)
    inv_balance = _investable_balance(portfolio, buffer_pct)

    # Flags
    flags = generate_flags(assets, allocation_status)

    return PortfolioAnalysis(
        client_name=portfolio.client_name,
        reference_month=f"{MONTH_NAMES_PT[month]} de {year}",
        total_invested=portfolio.total_invested,
        available_balance=portfolio.available_balance,
        total_patrimony=portfolio.total_patrimony,
        investable_balance=inv_balance,
        liquidity_buffer_pct=buffer_pct,
        advisor_name=portfolio.advisor_name,
        advisor_code=portfolio.advisor_code,
        assets=assets,
        portfolio_monthly_return_pct=_weighted_portfolio_return(assets),
        cdi_monthly_pct=benchmarks.cdi_monthly_pct,
        ipca_monthly_pct=benchmarks.ipca_monthly_pct,
        ibovespa_monthly_pct=benchmarks.ibovespa_monthly_pct,
        allocation_status=allocation_status,
        flags=flags,
    )
