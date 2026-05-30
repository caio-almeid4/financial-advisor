from pydantic import BaseModel


class AssetReturn(BaseModel):
    name: str
    asset_class: str  # "acoes", "fundos_multimercado", "fundos_acoes", "renda_fixa"
    allocation_pct: float
    monthly_return_pct: float | None  # None for Advisory funds (no CVM data)
    return_since_inception_pct: float
    monthly_vs_cdi: float | None  # monthly_return - cdi_monthly; None if no monthly data
    investment_date: str           # "DD/MM/YYYY" from source asset


class AllocationStatus(BaseModel):
    asset_class: str
    current_pct: float
    target_pct: float
    gap_pct: float  # current - target; positive = overweight, negative = underweight


class WatchlistItem(BaseModel):
    ticker: str
    current_price: float
    monthly_return_pct: float
    in_portfolio: bool


class PortfolioAnalysis(BaseModel):
    client_name: str
    reference_month: str          # e.g. "abril de 2025"
    total_invested: float         # sum of actual invested positions
    available_balance: float      # Saldo Disponível (idle cash)
    total_patrimony: float        # total_invested + available_balance
    investable_balance: float     # available_balance minus liquidity buffer
    liquidity_buffer_pct: float   # buffer % applied (e.g. 0.05 for moderate)
    advisor_name: str
    advisor_code: str

    assets: list[AssetReturn]
    portfolio_monthly_return_pct: float | None  # weighted avg; None if no assets have monthly data

    cdi_monthly_pct: float
    ipca_monthly_pct: float
    ibovespa_monthly_pct: float

    allocation_status: list[AllocationStatus]
    flags: list[str]
    watchlist: list[WatchlistItem]
