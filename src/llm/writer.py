import json
import time
from datetime import datetime

from dotenv import load_dotenv
from openai import OpenAI

from src.analysis.models import PortfolioAnalysis
from src.llm.models import PortfolioRecommendations
from src.observability import log_llm_call
from src.prompts import writer as prompts

load_dotenv()
client = OpenAI()


_MONTH_PT = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril",
    5: "maio", 6: "junho", 7: "julho", 8: "agosto",
    9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro",
}


def _today_pt() -> str:
    """Return today's date formatted in Brazilian Portuguese, e.g. '30 de maio de 2026'."""
    now = datetime.now()
    return f"{now.day} de {_MONTH_PT[now.month]} de {now.year}"


def _build_user_message(
    recommendations: PortfolioRecommendations,
    analysis: PortfolioAnalysis,
) -> str:
    return json.dumps({
        "client_name": analysis.client_name,
        "report_date": _today_pt(),
        "reference_month": analysis.reference_month,
        "total_invested": analysis.total_invested,
        "available_balance": analysis.available_balance,
        "investable_balance": analysis.investable_balance,
        "liquidity_buffer_pct": analysis.liquidity_buffer_pct,
        "portfolio_monthly_return_pct": analysis.portfolio_monthly_return_pct,
        "cdi_monthly_pct": analysis.cdi_monthly_pct,
        "ibovespa_monthly_pct": analysis.ibovespa_monthly_pct,
        "ipca_monthly_pct": analysis.ipca_monthly_pct,
        "observations": recommendations.observations,
        "recommendations": [r.model_dump() for r in recommendations.recommendations],
        "macro_impact": recommendations.macro_impact,
        "overall_assessment": recommendations.overall_assessment,
    }, ensure_ascii=False, indent=2)


def write_letter(
    recommendations: PortfolioRecommendations,
    analysis: PortfolioAnalysis,
) -> str:
    messages = [
        {"role": "system", "content": prompts.SYSTEM},
        {"role": "user", "content": _build_user_message(recommendations, analysis)},
    ]

    t0 = time.perf_counter()
    completion = client.chat.completions.create(
        model="gpt-5.4",
        messages=messages,
    )
    latency = time.perf_counter() - t0

    log_llm_call(
        stage="writer",
        model="gpt-5.4",
        messages=messages,
        response=completion,
        latency_s=latency,
    )

    return completion.choices[0].message.content
