import json
import time

from dotenv import load_dotenv
from openai import OpenAI

from src.analysis.models import PortfolioAnalysis
from src.ingestion.models import MacroAnalysis, RiskProfile
from src.llm.models import PortfolioRecommendations
from src.observability import log_llm_call
from src.prompts import recommendations as prompts

load_dotenv()
client = OpenAI()


def _build_user_message(
    analysis: PortfolioAnalysis,
    risk_profile: RiskProfile,
    macro: MacroAnalysis,
) -> str:
    return json.dumps({
        "investable_balance_brl": analysis.investable_balance,
        "portfolio_analysis": analysis.model_dump(exclude={"watchlist"}),
        "risk_profile": {
            "classification": risk_profile.classification,
            "compatible_products": risk_profile.compatible_products,
        },
        "macro_context": {
            "title": macro.title,
            "editorial_summary": macro.editorial_summary,
            "key_points": macro.key_points,
            "projections": macro.projections.model_dump(),
        },
    }, ensure_ascii=False, indent=2)


def generate_recommendations(
    analysis: PortfolioAnalysis,
    risk_profile: RiskProfile,
    macro: MacroAnalysis,
) -> PortfolioRecommendations:
    messages = [
        {"role": "system", "content": prompts.SYSTEM},
        {"role": "user", "content": _build_user_message(analysis, risk_profile, macro)},
    ]

    t0 = time.perf_counter()
    completion = client.beta.chat.completions.parse(
        model="gpt-4o",
        messages=messages,
        response_format=PortfolioRecommendations,
    )
    latency = time.perf_counter() - t0

    result = completion.choices[0].message.parsed
    log_llm_call(
        stage="recommendations",
        model="gpt-4o",
        messages=messages,
        response=completion,
        latency_s=latency,
        cot=result.reasoning if result else None,
    )

    return result
