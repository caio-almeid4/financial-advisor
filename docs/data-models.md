# Data Models (`src/ingestion/models.py`)

Todos os modelos são classes Pydantic — o que significa que os dados são validados automaticamente ao serem criados. Se o LLM retornar um número onde deveria haver um texto, o Pydantic lança um erro antes que o dado incorreto contamine o pipeline.

---

## Modelos de Portfólio

### `Stock`
Representa uma **ação individual** na carteira do cliente.

| Campo | Tipo | Exemplo |
|-------|------|---------|
| `ticker` | str | `"LREN3"` |
| `position_value` | float | `27812.04` (valor atual em R$) |
| `allocation_pct` | float | `8.91` (% da carteira) |
| `return_since_inception_pct` | float | `-41.7` (desde a compra — **não é retorno mensal**) |
| `investment_date` | str | `"22/04/2021"` |
| `average_price` | float | `29.05` (preço médio de compra) |
| `current_price` | float | `16.94` |
| `quantity` | int | `1642` |

### `Fund`
Representa um **fundo de investimento** na carteira.

| Campo | Tipo | Exemplo |
|-------|------|---------|
| `name` | str | `"Riza Lotus Plus Advisory FIC FIRF REF DI CP"` |
| `position_value` | float | `96178.73` |
| `allocation_pct` | float | `30.81` |
| `return_since_inception_pct` | float | `15.51` (**desde a aplicação — não é retorno mensal**) |
| `investment_date` | str | `"22/04/2021"` |
| `invested_amount` | float | `83267.36` (valor aplicado originalmente) |
| `current_value` | float | `95254.02` (valor líquido atual) |

> **Atenção:** O retorno mensal dos fundos é calculado via API da CVM (valor da cota atual vs. cota do mês anterior), não a partir deste campo.
> **Classificação:** a classe do fundo (`AssetReturn.asset_class`) é determinada em dois passos: (1) campo `CLASSE` do cadastro CVM (`lookup_fund_class()`), que retorna valores como `"Ações"`, `"Multimercado"`, `"Renda Fixa"`; (2) inferência por sufixo do nome como fallback para fundos Advisory ausentes da CVM. O mapeamento completo está em `calculator.py → _CVM_CLASS_MAP`.

### `FixedIncome`
Representa um ativo de **renda fixa** (CDB, LCI, LCA, Tesouro Direto, etc.).

| Campo | Tipo | Exemplo |
|-------|------|---------|
| `type` | str | `"CDB"` |
| `issuer` | str | `"Banco C6"` |
| `position_value` | float | `40478.75` |
| `allocation_pct` | float | `12.97` |
| `invested_amount` | float | `30000.0` |
| `rate` | str | `"IPCA+5.45%"` |
| `investment_date` | str | `"09/11/2023"` |
| `maturity_date` | str | `"05/09/2024"` |

### `Portfolio`
**Objeto raiz** que agrega toda a carteira do cliente.

| Campo | Conteúdo |
|-------|----------|
| `client_name` | Nome do cliente |
| `account` | Número da conta XP |
| `reference_date` | Data do snapshot da carteira |
| `total_invested` | Patrimônio total em R$ |
| `stocks` | Lista de `Stock` |
| `funds` | Lista de `Fund` |
| `fixed_income` | Lista de `FixedIncome` |

---

## Modelos de Perfil de Risco

### `TargetAllocation`
Os **percentuais ideais por classe de ativo** para o perfil do cliente, extraídos do documento de perfil pelo LLM (Stage 0). Usados no Stage 1 para calcular gaps entre alocação atual e ideal.

| Campo | Exemplo (Moderado) |
|-------|--------------------|
| `acoes_pct` | `0.20` |
| `renda_fixa_pct` | `0.30` |
| `fundos_multimercado_pct` | `0.35` |
| `fundos_acoes_pct` | `0.15` |

> Em produção, esses valores seriam definidos pelo time de research da XP, não extraídos por LLM.

### `RiskProfile`
O **perfil de risco completo** do cliente, parsado do TXT pelo LLM de ingestão.

| Campo | Conteúdo |
|-------|----------|
| `client_name` | Nome do cliente |
| `classification` | `"Moderado"` / `"Conservador"` / `"Arrojado"` |
| `description` | Descrição qualitativa do perfil |
| `compatible_products` | Lista de produtos compatíveis |
| `target_allocation` | Objeto `TargetAllocation` extraído pelo LLM |

---

## Modelos de Análise Macro

### `MacroProjections`
Os **números quantitativos** extraídos da análise macro da XP. São injetados deterministicamente no pipeline — o LLM nunca "inventa" esses números.

| Campo | Exemplo |
|-------|---------|
| `ipca_2025` | `6.1` (%) |
| `ipca_2026` | `4.5` (%) |
| `selic_terminal` | `15.5` (% a.a.) |
| `gdp_growth_2025` | `2.0` (%) |
| `usd_brl_end_2025` | `6.20` |

### `MacroAnalysis`
A **análise macro completa**, usada como contexto no Stage 1 (recomendações). Apenas excertos relevantes são passados ao LLM — não o documento inteiro — para evitar que dados numéricos precisos se percam no meio de muito texto.

| Campo | Conteúdo |
|-------|----------|
| `date` | Data do relatório |
| `title` | Título |
| `key_points` | Bulletpoints principais |
| `projections` | Objeto `MacroProjections` |
| `editorial_summary` | Parágrafo editorial resumido |

---

## Modelos de Dados de Mercado (`src/data/market.py`)

> Estes são `dataclass` (não Pydantic) — são dados internos confiáveis, não entrada de LLM.

### `FundMonthlyData`
Resultado do lookup de cota de um fundo via CVM.

| Campo | Tipo | Observação |
|-------|------|------------|
| `name` | str | Nome do fundo (igual ao portfólio) |
| `cnpj` | str \| None | `None` para fundos Advisory (não estão na CVM pública) |
| `cvm_class` | str \| None | Campo `CLASSE` do cadastro CVM — ex: `"Ações"`, `"Multimercado"`, `"Renda Fixa"`. `None` para fundos Advisory. Usado por `classify_fund()` como source of truth |
| `end_of_month_nav` | float \| None | Cota no último dia útil do mês |
| `end_of_prev_month_nav` | float \| None | Cota no último dia útil do mês anterior |
| `monthly_return_pct` | float \| None | `(nav_atual - nav_anterior) / nav_anterior × 100`. `None` se fundo não está na CVM |

### `StockMonthlyData`
Preços de uma ação via Yahoo Finance.

| Campo | Tipo | Observação |
|-------|------|------------|
| `ticker` | str | Ex: `"LREN3"` |
| `end_of_month_price` | float | Preço de fechamento no último dia útil do mês |
| `end_of_prev_month_price` | float | Preço de fechamento no último dia útil do mês anterior |
| `monthly_return_pct` | float | Retorno calculado deterministicamente |

### `BenchmarkData`
Benchmarks do mês, buscados de fontes externas.

| Campo | Fonte |
|-------|-------|
| `cdi_monthly_pct` | BACEN série 12 (CDI diário composto) |
| `ipca_monthly_pct` | BACEN série 433 |
| `ibovespa_monthly_pct` | Yahoo Finance `^BVSP` |

---

## Modelos de Análise (`src/analysis/models.py`)

### `AssetReturn`
Resultado da análise mensal de **um ativo** da carteira.

| Campo | Tipo | Observação |
|-------|------|------------|
| `name` | str | Ticker (ações) ou nome do fundo/emissor |
| `asset_class` | str | `"acoes"`, `"renda_fixa"`, `"fundos_multimercado"`, `"fundos_acoes"` |
| `allocation_pct` | float | % da carteira total |
| `monthly_return_pct` | float \| None | `None` para fundos Advisory sem cota pública |
| `return_since_inception_pct` | float | Retorno acumulado desde a compra/aplicação |
| `monthly_vs_cdi` | float \| None | `monthly_return_pct - cdi_monthly_pct`. `None` se não há dado mensal |

### `PortfolioAnalysis`
Saída completa do estágio de análise — entrada do LLM Stage 1.

| Campo | Tipo | Observação |
|-------|------|------------|
| `portfolio_monthly_return_pct` | float \| None | Média ponderada dos retornos mensais dos ativos **com dado disponível**. `None` somente se nenhum ativo tem retorno mensal. O label no PDF indica a cobertura (ex: "Retorno (43% da carteira)") |
| `allocation_status` | list[AllocationStatus] | Gap entre alocação atual e alvo por classe |
| `flags` | list[str] | Alertas gerados por regras determinísticas em `flags.py` |
| `watchlist` | list[WatchlistItem] | Ações candidatas a recomendação de compra (lidas do CSV) |
