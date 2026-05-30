from pydantic import BaseModel, model_validator


class Stock(BaseModel):
    ticker: str
    position_value: float
    allocation_pct: float
    return_since_inception_pct: float
    investment_date: str
    average_price: float
    current_price: float
    quantity: int


class Fund(BaseModel):
    name: str
    position_value: float
    allocation_pct: float
    return_since_inception_pct: float
    investment_date: str
    invested_amount: float
    current_value: float


class FixedIncome(BaseModel):
    type: str
    issuer: str
    position_value: float
    allocation_pct: float
    invested_amount: float
    rate: str
    investment_date: str
    maturity_date: str


class Portfolio(BaseModel):
    client_name: str
    account: str
    reference_date: str
    total_invested: float        # sum of actual invested positions (Ações + Fundos + Renda Fixa)
    available_balance: float     # Saldo Disponível (idle cash)
    total_patrimony: float       # total_invested + available_balance
    advisor_name: str            # Nome do assessor
    advisor_code: str            # Código do Assessor
    stocks: list[Stock]
    funds: list[Fund]
    fixed_income: list[FixedIncome]


class TargetAllocation(BaseModel):
    acoes_pct: float
    renda_fixa_pct: float
    fundos_multimercado_pct: float
    fundos_acoes_pct: float

    @model_validator(mode="after")
    def must_sum_to_one(self):
        total = self.acoes_pct + self.renda_fixa_pct + self.fundos_multimercado_pct + self.fundos_acoes_pct
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Target allocation must sum to 1.0, got {total:.4f}")
        return self


class RiskProfile(BaseModel):
    client_name: str
    classification: str
    description: str
    compatible_products: list[str]
    target_allocation: TargetAllocation


class MacroProjections(BaseModel):
    ipca_2025: float
    ipca_2026: float
    selic_terminal: float
    gdp_growth_2025: float
    usd_brl_end_2025: float


class MacroAnalysis(BaseModel):
    date: str
    title: str
    key_points: list[str]
    projections: MacroProjections
    editorial_summary: str
