"""
Entry point for the XP AI Financial Advisor pipeline.

Usage:
    uv run python main.py --input-dir inputs/albert

Each input directory must contain three files:
    portfolio.txt      — client portfolio TXT export
    risk_profile.txt   — client risk/suitability profile TXT
    macro.txt          — XP monthly macro analysis TXT

Defaults to inputs/albert so bare `uv run python main.py` works out of the box.
"""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.observability import setup_logging, log_event
from src.analysis.calculator import analyze_portfolio
from src.data.market import (
    get_benchmarks,
    get_fund_monthly_data,
    get_stock_monthly_data,
    lookup_fund_class,
    lookup_fund_cnpj,
)
from src.ingestion.parser import load_all_inputs
from src.ingestion.reader import find_input
from src.llm.recommendations import generate_recommendations
from src.llm.writer import write_letter
from src.report.generator import generate_report, generate_advisor_report

_ROOT = Path(__file__).parent


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="XP AI Financial Advisor — generate a monthly PDF report for a client."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        dest="input_dir",
        default=_ROOT / "inputs" / "albert",
        help="Folder with portfolio, risk_profile, and macro files (.pdf or .txt, auto-detected).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        dest="output_dir",
        default=_ROOT / "output",
        help="Directory where the PDFs will be saved.",
    )
    return parser.parse_args()


def _parse_reference_date(date_str: str) -> tuple[int, int]:
    """Returns (year, month) from various date string formats."""
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            d = datetime.strptime(date_str.strip(), fmt)
            return d.year, d.month
        except ValueError:
            continue
    raise ValueError(
        f"Could not parse reference date {date_str!r}. "
        "Expected DD/MM/YYYY or YYYY-MM-DD."
    )


_PIPELINE_STAGES = (
    "Parsing input files (LLM)",
    "Fetching stock prices (Yahoo Finance)",
    "Fetching fund NAVs (CVM) and benchmarks",
    "Analysing portfolio (deterministic)",
    "Generating recommendations (LLM gpt-4o)",
    "Writing client letter (LLM gpt-4o)",
    "Generating PDF reports (Playwright)",
)


def _step(n: int, label: str) -> None:
    print(f"  [{n}/{len(_PIPELINE_STAGES)}] {label}...", flush=True)



def main() -> None:
    args = _parse_args()

    try:
        portfolio_path    = find_input(args.input_dir, "portfolio")
        risk_profile_path = find_input(args.input_dir, "risk_profile")
        macro_path        = find_input(args.input_dir, "macro")
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    setup_logging(_ROOT / "logs", run_id)
    t0 = time.time()

    print("\nXP AI Financial Advisor — generating monthly report\n")

    # ── Stage 1: Ingestion ──────────────────────────────────────────────────
    _step(1, "Parsing input files (LLM)")
    portfolio, risk_profile, macro = load_all_inputs(
        portfolio_path, risk_profile_path, macro_path
    )
    year, month = _parse_reference_date(portfolio.reference_date)
    print(
        f"         Client  : {portfolio.client_name}\n"
        f"         Period  : {month:02d}/{year}\n"
        f"         Profile : {risk_profile.classification}\n"
        f"         Advisor : {portfolio.advisor_name} ({portfolio.advisor_code})\n"
        f"         Saldo   : R${portfolio.available_balance:,.2f} disponível"
    )
    log_event("ingestion",
              portfolio=portfolio.model_dump(),
              risk_profile=risk_profile.model_dump(),
              macro=macro.model_dump())

    # ── Market data ─────────────────────────────────────────────────────────
    _step(2, "Fetching stock prices (Yahoo Finance)")
    stock_data = {}
    for stock in portfolio.stocks:
        try:
            stock_data[stock.ticker] = get_stock_monthly_data(stock.ticker, year, month)
            print(f"           {stock.ticker}: {stock_data[stock.ticker].monthly_return_pct:+.2f}%")
        except Exception as e:
            print(f"           {stock.ticker}: failed ({e})", file=sys.stderr)

    _step(3, "Fetching fund NAVs (CVM) and benchmarks")
    fund_data = {}
    for fund in portfolio.funds:
        cnpj = lookup_fund_cnpj(fund.name)
        cvm_class = lookup_fund_class(fund.name)
        fund_data[fund.name] = get_fund_monthly_data(
            fund.name, cnpj, cvm_class, year, month
        )
        status = (
            f"{fund_data[fund.name].monthly_return_pct:+.2f}%"
            if fund_data[fund.name].monthly_return_pct is not None
            else "no CVM data (Advisory fund)"
        )
        print(f"           {fund.name[:40]}: {status}")

    benchmarks = get_benchmarks(year, month)
    print(
        f"         CDI    : {benchmarks.cdi_monthly_pct:+.2f}%\n"
        f"         IPCA   : {benchmarks.ipca_monthly_pct:+.2f}%\n"
        f"         Ibov   : {benchmarks.ibovespa_monthly_pct:+.2f}%"
    )

    # ── Analysis ────────────────────────────────────────────────────────────
    _step(4, "Analysing portfolio (deterministic)")
    analysis = analyze_portfolio(
        portfolio=portfolio,
        risk_profile=risk_profile,
        stock_data=stock_data,
        fund_data=fund_data,
        benchmarks=benchmarks,
        ipca_monthly_pct=benchmarks.ipca_monthly_pct,
        watchlist_path=args.watchlist,
        year=year,
        month=month,
    )
    log_event("analysis", portfolio_analysis=analysis.model_dump())
    print(
        f"         Investível: R${analysis.investable_balance:,.2f} "
        f"(buffer {analysis.liquidity_buffer_pct*100:.0f}%)"
    )
    if analysis.flags:
        print("         Flags  :", *analysis.flags, sep="\n                  ")

    # ── LLM Stage 1: Recommendations ────────────────────────────────────────
    _step(5, "Generating recommendations (LLM gpt-4o)")
    recommendations = generate_recommendations(analysis, risk_profile, macro)
    print(f"         {len(recommendations.recommendations)} recommendation(s) generated")

    # ── LLM Stage 2: Letter ─────────────────────────────────────────────────
    _step(6, "Writing client letter (LLM gpt-4o)")
    letter = write_letter(recommendations, analysis)

    # ── PDF reports ──────────────────────────────────────────────────────────
    _step(7, "Generating PDF reports (Playwright)")
    pdf_path    = generate_report(letter, analysis, recommendations, output_dir=args.output_dir)
    advisor_pdf = generate_advisor_report(letter, analysis, recommendations, output_dir=args.output_dir)

    elapsed = time.time() - t0
    print(f"\n  Client PDF  : {pdf_path}")
    print(f"  Advisor PDF : {advisor_pdf}")
    print(f"  Total time  : {elapsed:.1f}s\n")


if __name__ == "__main__":
    main()
