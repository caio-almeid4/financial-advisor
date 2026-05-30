import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

from src.observability import log_llm_call
from src.prompts import macro_analysis as macro_prompts
from src.prompts import portfolio as portfolio_prompts
from src.prompts import risk_profile as risk_prompts

from .models import MacroAnalysis, Portfolio, RiskProfile

client = OpenAI()
_MODEL = "gpt-4o-mini"


def _parse(model_class, system_prompt: str, text: str, stage: str):
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": text},
    ]
    t0 = time.perf_counter()
    completion = client.beta.chat.completions.parse(
        model=_MODEL,
        messages=messages,
        response_format=model_class,
    )
    latency = time.perf_counter() - t0

    log_llm_call(
        stage=stage,
        model=_MODEL,
        messages=messages,
        response=completion,
        latency_s=latency,
    )

    return completion.choices[0].message.parsed


def parse_portfolio(txt_path: Path) -> Portfolio:
    return _parse(Portfolio, portfolio_prompts.SYSTEM,
                  txt_path.read_text(encoding="utf-8"), "ingestion_portfolio")


def parse_risk_profile(txt_path: Path) -> RiskProfile:
    return _parse(RiskProfile, risk_prompts.SYSTEM,
                  txt_path.read_text(encoding="utf-8"), "ingestion_risk_profile")


def parse_macro_analysis(txt_path: Path) -> MacroAnalysis:
    return _parse(MacroAnalysis, macro_prompts.SYSTEM,
                  txt_path.read_text(encoding="utf-8"), "ingestion_macro")


def load_all_inputs(
    portfolio_path: Path,
    risk_profile_path: Path,
    macro_path: Path,
) -> tuple[Portfolio, RiskProfile, MacroAnalysis]:
    return (
        parse_portfolio(portfolio_path),
        parse_risk_profile(risk_profile_path),
        parse_macro_analysis(macro_path),
    )
