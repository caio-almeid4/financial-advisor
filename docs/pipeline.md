# Pipeline Completo

Fluxo de dados do início ao fim, estágio por estágio.

---

## Visão Geral

```
TXT (portfólio)     ──┐
TXT (perfil risco)  ──┤── [Ingestion LLM] ──► Pydantic models validados
TXT (macro)         ──┘         │
                                ▼
                        [Market Data APIs]
                    Yahoo Finance → preços de ações + Ibovespa
                    CVM → cotas de fundos (quando disponível)
                    BACEN → CDI + IPCA mensais
                                │
                                ▼
                        [Analysis — Python puro]
                    calcular retornos mensais por ativo
                    calcular retorno ponderado da carteira
                    calcular gaps de alocação vs. target
                    gerar flags determinísticas
                    carregar watchlist
                    output: PortfolioAnalysis (Pydantic)
                                │
                                ▼
                        [Stage 1 — LLM gpt-4o, structured output]
                    input: PortfolioAnalysis + perfil + macro (JSON)
                    output: PortfolioRecommendations (Pydantic)
                                │
                                ▼
                        [Stage 2 — LLM gpt-4o, texto livre]
                    input: PortfolioRecommendations + métricas-chave
                    output: carta em português (string)
                                │
                                ▼
                        [Report — Python]
                    gerar gráficos (matplotlib → base64)
                    renderizar template (Jinja2 → HTML)
                    converter para PDF (WeasyPrint)
```

---

## Estágios em Detalhe

### Ingestion (`src/ingestion/`)

**Responsabilidade:** converter TXTs desformatados em objetos Python validados.

| Arquivo | Função |
|---------|--------|
| `models.py` | Pydantic models: `Portfolio`, `RiskProfile`, `MacroAnalysis` e sub-modelos |
| `parser.py` | Chama OpenAI `gpt-4o-mini` com structured output para cada TXT |

**Prompts usados:** `src/prompts/portfolio.py`, `risk_profile.py`, `macro_analysis.py`

**Por que LLM aqui:** os TXTs são exports desestruturados de uma plataforma web — o portfólio do Albert, por exemplo, tem o nome do fundo Ibiuna aparecendo *após* seus dados numéricos. LLM lida com essa desordem; regex não.

---

### Market Data (`src/data/market.py`)

**Responsabilidade:** buscar dados de mercado externos para o mês de referência.

| Função | Fonte | O que retorna |
|--------|-------|---------------|
| `get_stock_monthly_data()` | Yahoo Finance | Preço fim do mês atual e anterior → retorno mensal % |
| `get_fund_monthly_data()` | CVM `inf_diario_fi` | Cota fim do mês atual e anterior → retorno mensal % |
| `lookup_fund_cnpj()` | CVM `cad_fi.csv` | CNPJ a partir do nome do fundo (fuzzy match) |
| `get_cdi_monthly_pct()` | BACEN série 12 | CDI composto do mês (%) |
| `get_ipca_monthly_pct()` | BACEN série 433 | IPCA do mês (%) |
| `get_ibovespa_monthly_pct()` | Yahoo Finance `^BVSP` | Retorno mensal do Ibovespa (%) |
| `get_cdb_monthly_return_pct()` | Calculado | Retorno mensal do CDB IPCA+spread |
| `get_benchmarks()` | Agrega as três anteriores | `BenchmarkData` |

**Limitação conhecida:** fundos com sufixo "Advisory" são veículos exclusivos XP, não registrados no cadastro público da CVM. `lookup_fund_cnpj()` retorna `None` para eles → `monthly_return_pct` será `None` → pipeline continua usando `return_since_inception_pct` como contexto.

---

### Analysis (`src/analysis/`)

**Responsabilidade:** toda a matemática do pipeline. Zero LLM.

#### `calculator.py`

| Função | O que faz |
|--------|-----------|
| `classify_fund()` | Infere classe do fundo pelo sufixo do nome (FIA→fundos_acoes, FIRF→renda_fixa, FIM→fundos_multimercado) |
| `_current_allocation()` | Soma alocação % por classe de ativo a partir do portfólio |
| `_allocation_status()` | Compara alocação atual com target do perfil → lista de `AllocationStatus` |
| `_weighted_portfolio_return()` | Média ponderada dos retornos mensais. Retorna `None` se menos de 50% da carteira tem dado mensal |
| `load_watchlist()` | Lê `profitability_calc_wip.csv` → lista de `WatchlistItem` com retorno mensal calculado |
| `analyze_portfolio()` | Orquestra tudo → retorna `PortfolioAnalysis` |

#### `flags.py`

Regras determinísticas que geram alertas textuais. Três categorias:

| Flag | Condição | Exemplo |
|------|----------|---------|
| Perda severa desde a compra | `return_since_inception_pct < -40%` | "HAPV3 acumula -74.6% desde a compra" |
| Gap de alocação | `abs(gap_pct) > 10pp` | "acoes está 15.0pp abaixo da alocação-alvo" |
| Abaixo do CDI no mês | `monthly_vs_cdi < 0` | "LREN3 rendeu abaixo do CDI no mês (0.50% vs CDI)" |

---

### LLM Stage 1 — Recomendações (`src/llm/recommendations.py`)

**Responsabilidade:** analisar o `PortfolioAnalysis` e gerar observações e recomendações estruturadas.

- **Modelo:** `gpt-4o` (reasoning mais robusto para análise financeira)
- **Output:** `PortfolioRecommendations` (Pydantic structured output)
- **Input (JSON):** `PortfolioAnalysis` completo + `risk_profile.classification` + `macro.projections` e `macro.key_points`
- **Prompt:** RICES — Role, Instructions, Context, Examples (sem Specific, pois o schema Pydantic define o formato)

**Regras do prompt:**
- Só recomenda venda/redução de ativos que existem na carteira
- Só recomenda compra de ativos da watchlist com `in_portfolio=False`
- Não inventa números — usa apenas o que está no JSON de entrada
- Escreve em inglês (output interno, não enviado ao cliente)

#### Output model (`src/llm/models.py`)

```python
class AssetRecommendation(BaseModel):
    action: str    # "reduzir", "aumentar", "manter", "considerar_venda", "considerar_compra"
    asset: str
    rationale: str

class PortfolioRecommendations(BaseModel):
    observations: list[str]
    recommendations: list[AssetRecommendation]
    macro_impact: str
    overall_assessment: str
```

---

### LLM Stage 2 — Redação da Carta (`src/llm/writer.py`)

**Responsabilidade:** redigir a carta ao cliente em português. Só escreve — não analisa.

- **Modelo:** `gpt-4o`
- **Output:** string (texto livre da carta)
- **Input (JSON):** `PortfolioRecommendations` + métricas-chave do `PortfolioAnalysis`
- **Prompt:** RICES — inclui formato esperado da carta e exemplos de bom/mau texto

**Formato da carta:**
1. Cabeçalho: cidade, data, saudação
2. Parágrafo de abertura: performance geral do mês
3. Corpo: 2-3 parágrafos (detalhes, macro, recomendações)
4. Encerramento: próximos passos + oferta de conversa
5. Assinatura: "Seu assessor XP" (placeholder)

---

### Report (`src/report/`) — A IMPLEMENTAR

**Responsabilidade:** transformar a carta e os dados em um PDF profissional de 2 páginas.

Componentes planejados:
- `charts.py`: gerar gráficos matplotlib → base64 PNG
  - Gráfico 1: Alocação atual vs. alvo (barras agrupadas por classe)
  - Gráfico 2: Retorno mensal por ativo vs. CDI (barras horizontais)
- `template.html`: template Jinja2 com layout da carta + espaços para gráficos
- `generator.py`: orquestra Jinja2 → HTML → WeasyPrint → PDF

---

## Modelos Pydantic por Estágio

```
Ingestion          Analysis           LLM Stage 1        Report
──────────         ────────           ───────────        ──────
Portfolio     →    PortfolioAnalysis  →  PortfolioRec  →  PDF
RiskProfile                              (+ str letter)
MacroAnalysis
```

---

## Configuração e Dependências

- **Python:** 3.12
- **LLM:** OpenAI API (`OPENAI_API_KEY` em `.env`)
- **Stack:** openai, pydantic, yfinance, httpx, pandas, rapidfuzz, matplotlib, jinja2, weasyprint
- **Testes:** pytest (`uv run pytest -m "not integration"` para unit tests)
