# XP AI Financial Advisor

POC of an AI-powered pipeline that generates personalized monthly investment reports for XP Investimentos clients. Given three input files, it produces two PDFs in under 60 seconds: a client-facing letter with charts and an internal advisor summary.

---

## How it works

```mermaid
flowchart TD
    subgraph inputs["Input files (inputs/&lt;client&gt;/)"]
        P[portfolio.pdf/.txt]
        R[risk_profile.pdf/.txt]
        M[macro.pdf/.txt]
        W[watchlist.csv\noptional]
    end

    subgraph stage1["Stage 1 — Ingestion (gpt-5.4-mini)"]
        P --> PB[pdfplumber\nor read_text]
        R --> PB
        M --> PB
        PB --> PP[Portfolio parser]
        PB --> RP[Risk profile parser]
        PB --> MP[Macro analysis parser]
    end

    subgraph stage2["Stage 2 & 3 — Market data"]
        PP --> YF[Yahoo Finance\nstock returns · Ibovespa]
        PP --> CVM[CVM API\nfund daily NAVs]
        BCB[BCB API\nCDI · IPCA]
        W --> WL[load_watchlist\nenrich with live prices]
    end

    subgraph stage4["Stage 4 — Portfolio analysis (deterministic)"]
        YF --> CALC[Calculator]
        CVM --> CALC
        BCB --> CALC
        PP --> CALC
        RP --> CALC
        CALC --> FLAGS[Flags\ndrawdown · CDI miss · allocation gap]
        CALC --> LIQ[Liquidity buffer\nequity % → reserve %]
        CALC --> ALLOC[Allocation gaps\nvs. target]
    end

    subgraph stage5["Stage 5 — Recommendations (gpt-5.4)"]
        FLAGS --> REC[Chain-of-thought\nrecommendations]
        LIQ --> REC
        ALLOC --> REC
        MP --> REC
        RP --> REC
        WL --> REC
    end

    subgraph stage6["Stage 6 — Letter (gpt-4.1)"]
        REC --> LETTER[Client letter\nBrazilian Portuguese\nfirst-person advisor voice]
    end

    subgraph stage7["Stage 7 — PDF generation (Playwright)"]
        LETTER --> CLIENT[report_&lt;client&gt;_&lt;month&gt;.pdf\nLetter · SVG charts · sign-off]
        REC --> ADVISOR[advisor_&lt;client&gt;_&lt;month&gt;.pdf\nInternal one-pager · ticker badges]
    end

    subgraph obs["Observability"]
        stage1 & stage5 & stage6 --> LOG[logs/run_YYYYMMDD.ndjson\ntokens · latency · CoT]
    end
```

| # | Stage | Model | Description |
|---|-------|-------|-------------|
| 1 | Ingestion | gpt-5.4-mini | Parses portfolio, risk profile, and macro files (.pdf or .txt via pdfplumber) |
| 2 | Stock prices | — | Monthly returns fetched from Yahoo Finance |
| 3 | Fund NAVs & benchmarks | — | Daily NAVs from CVM public API; CDI/IPCA from BCB; Ibovespa from Yahoo Finance |
| 4 | Portfolio analysis | — | Deterministic: allocation gaps, liquidity buffer, flags, watchlist enrichment |
| 5 | Recommendations | gpt-5.4 | Chain-of-thought recommendations; ticker suggestions from advisor watchlist |
| 6 | Client letter | gpt-4.1 | Personalized letter in Brazilian Portuguese; ticker_suggestion excluded |
| 7 | PDF generation | — | Playwright (Chromium) renders two PDFs with inline SVG charts |

**Outputs:**
- `output/report_<client>_<month>.pdf` — client-facing report (letter + charts, 2 pages)
- `output/advisor_<client>_<month>.pdf` — internal one-page advisor briefing

---

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- OpenAI API key

---

## Setup

```bash
# Install dependencies
uv sync

# Install Chromium for Playwright (one-time)
uv run playwright install chromium

# Configure API key
cp .env.example .env
# then open .env and replace sk-... with your actual key
```

---

## Usage

```bash
# Run with the sample client (inputs/albert/)
uv run python main.py

# Run with a different client
uv run python main.py --input-dir inputs/joao

# Custom output directory
uv run python main.py --input-dir inputs/albert --output-dir /tmp/reports
```

---

## Input format

Each client folder under `inputs/` must contain three files exported from XP's systems, plus an optional watchlist.

Both `.pdf` and `.txt` are accepted — PDF takes priority if both exist, and mixing is allowed (e.g. `portfolio.pdf` + `macro.txt`).

```
inputs/
  albert/
    portfolio.pdf        # or portfolio.txt
    risk_profile.pdf     # or risk_profile.txt
    macro.pdf            # or macro.txt
    watchlist.csv        # optional — advisor-curated ticker list
```

### watchlist.csv format

```csv
Asset class,Asset,Current price,Last month price
Stocks,ITUB4,27.8,26.9
Stocks,PETR4,37.12,34.8
```

CSV prices are ignored at runtime — monthly returns are always re-fetched from Yahoo Finance for consistency with the rest of the pipeline. When present, the recommendations LLM picks tickers from this list to populate `ticker_suggestion`, shown as a badge in the **advisor PDF only**.

---

## Project structure

```
main.py                  # pipeline orchestration + CLI
src/
  ingestion/             # LLM-based parsers + PDF/TXT reader
  analysis/              # deterministic calculator, flags, liquidity buffer
  llm/                   # recommendations and letter writing
  prompts/               # system prompts for each LLM stage
  report/                # Playwright PDF generator, SVG charts, HTML templates
  observability/         # structured NDJSON logging per run
inputs/                  # one folder per client
assets/                  # static assets (logo)
docs/                    # architecture, decisions, data models, roadmap
```

---

## Advisor Dashboard (concept)

![Advisor Dashboard](assets/dashboard.png)

---

## Tests

```bash
uv run pytest tests/ -m "not integration" -q
```

---

## Observability

Every pipeline run writes a structured log to `logs/run_YYYYMMDD_HHMMSS.ndjson`. Each line is a JSON object capturing stage, model, token counts, latency, and the full chain-of-thought for LLM calls.

```bash
# Quick inspection
cat logs/run_*.ndjson | jq 'select(.msg=="llm_call") | {stage, latency_s, input_tokens, output_tokens}'
```
