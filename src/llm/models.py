from pydantic import BaseModel, Field


class AssetRecommendation(BaseModel):
    action: str   # "reduzir", "aumentar", "manter", "considerar_venda", "considerar_compra"
    asset: str    # ticker, fund name, or asset class
    rationale: str


class PortfolioRecommendations(BaseModel):
    # First field — model reasons step-by-step before producing structured output.
    # Generated before observations/recommendations so the model "thinks out loud"
    # prior to committing to any conclusion. Captured in logs as chain-of-thought.
    reasoning: str = Field(
        description=(
            "Step-by-step internal analysis: review each asset's performance and flags, "
            "assess allocation gaps, connect macro context to portfolio positions, "
            "identify what action (if any) is warranted for each item, and evaluate "
            "regulatory constraints before drafting recommendations."
        )
    )
    observations: list[str]
    recommendations: list[AssetRecommendation]
    macro_impact: str       # how macro context affects this specific portfolio
    overall_assessment: str # 1-2 sentence summary of the portfolio's health
