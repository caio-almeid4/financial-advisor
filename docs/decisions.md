# Decisões Arquiteturais

Registro das decisões tomadas e o raciocínio por trás de cada uma.

---

## Artefatos de Saída do Pipeline

O pipeline gera três artefatos por execução:

| Arquivo | Audiência | Tooling |
|---|---|---|
| `report_{client}_{month}.pdf` | Cliente — relatório formal | Playwright (Chromium) |
| `report_{client}_{month}.html` | Cliente — versão interativa hospedada | HTML/CSS + Chart.js |
| `advisor_{client}_{month}.pdf` | Assessor — resumo executivo interno | Playwright (Chromium) |

### Por que Playwright em vez de WeasyPrint

WeasyPrint usa um renderer próprio com suporte parcial a CSS moderno. Playwright usa o engine real do Chromium — renderiza qualquer CSS, Google Fonts, JavaScript (Chart.js, D3.js), gradientes, sombras. A qualidade visual do PDF é significativamente superior. O HTML é "fotografado" pelo Chromium antes de virar PDF, garantindo fidelidade perfeita ao design.

### PDF do cliente vs. HTML interativo

São o mesmo conteúdo em dois formatos: o PDF é a versão formal para envio/arquivo; o HTML é a versão digital com gráficos interativos (hover, zoom, filtros). O pipeline gera o HTML primeiro, depois o Playwright o converte para PDF.

### Página HTML hospedada

Em produção: URL real (`https://relatorio.xp.com.br/{client}/{month}`) gerada pelo pipeline e incorporada como link/QR code no PDF.  
No POC: pipeline levanta `python -m http.server` em `output/` e imprime `http://localhost:8080/report_{client}_{month}.html`. A troca para produção é só a base URL — nenhuma mudança de lógica.

### Assessor — dados capturados do documento

`advisor_name` e `advisor_code` são extraídos pelo LLM de ingestão diretamente do TXT do portfólio (ex: "Antonio Bicudo", "A7699"). Adicionados ao modelo `Portfolio` — zero configuração manual necessária.

### Assessor — conteúdo do resumo executivo

Uma página, sem texto corrido:
- Saldo investível calculado (após reserva de liquidez)
- Flags detectadas pelo sistema determinístico
- Recomendações geradas (ação + ativo + racional em uma linha)
- Próximos passos sugeridos ao cliente na carta

### Deep link para o app XP (roadmap)

**O que faria com mais tempo:** cada recomendação no PDF/HTML teria um botão "Executar no app XP" com um deep link para o aplicativo da XP abrindo direto na tela de operação correspondente (ex: compra de fundo, aporte em renda fixa). No POC, o link é fake (`xpinvestimentos://operacao?tipo=aporte&fundo=...`) mas demonstra a integração possível com o app mobile — o objetivo é reduzir o atrito entre a recomendação e a execução, aumentando o share of wallet.

---

## Sistema de Logs

O pipeline grava um arquivo NDJSON (uma linha = um objeto JSON) por execução em `logs/run_YYYYMMDD_HHMMSS.ndjson`. Cada entrada tem `ts` (ISO 8601 UTC), `lvl`, `msg` e campos extras por tipo.

### Entradas por run

| `msg` | `stage` | O que captura |
|---|---|---|
| `logging_initialized` | — | Caminho do arquivo de log e `run_id` |
| `llm_call` | `ingestion_portfolio` | Prompt enviado + `Portfolio` parseado (`model_dump`) + tokens + latência |
| `llm_call` | `ingestion_risk_profile` | Prompt enviado + `RiskProfile` parseado + tokens + latência |
| `llm_call` | `ingestion_macro` | Prompt enviado + `MacroAnalysis` parseada + tokens + latência |
| `pipeline_event` | `ingestion` | Objetos consolidados: `portfolio`, `risk_profile`, `macro` (após parse das 3 LLM calls) |
| `pipeline_event` | `analysis` | `PortfolioAnalysis` completo: retornos por ativo, gaps de alocação, flags, watchlist |
| `llm_call` | `recommendations` | Prompt + recomendações estruturadas + **`cot`** (chain-of-thought) + tokens + latência |
| `llm_call` | `writer` | Prompt + preview da carta (500 chars) + tokens + latência |

### Chain-of-thought (CoT)

O campo `reasoning` é o **primeiro campo** de `PortfolioRecommendations`. Como a OpenAI gera campos estruturados em ordem, o modelo preenche o raciocínio passo a passo antes de comprometer observações e recomendações — o equivalente a "pensar em voz alta" antes de responder. O conteúdo desse campo aparece no log como `cot` na entrada `recommendations`.

### Formato de cada entrada `llm_call`

```json
{
  "ts": "2026-05-29T23:07:19Z",
  "lvl": "INFO",
  "msg": "llm_call",
  "stage": "recommendations",
  "model": "gpt-4o",
  "latency_s": 8.8,
  "input_tokens": 2555,
  "output_tokens": 835,
  "total_tokens": 3390,
  "cot": "The portfolio is overallocated to fixed income...",
  "messages": [{"role": "system", ...}, {"role": "user", ...}],
  "response": { ... }
}
```

### Onde fica

```
logs/
  run_20260529_230719.ndjson   ← um arquivo por execução
```

Para inspecionar rapidamente: `cat logs/run_*.ndjson | jq 'select(.msg=="llm_call") | {stage, latency_s, input_tokens, output_tokens}'`

---

## Stack

| Decisão | Escolha | Motivo |
|---------|---------|--------|
| Linguagem | Python 3.12 | Melhor suporte de libs vs. 3.14 (especialmente WeasyPrint); 3.12 é a versão estável mais recente |
| LLM | OpenAI API | Definido pela XP |
| Structured outputs | Pydantic v2 | Valida automaticamente o JSON retornado pelo LLM — erros explodem cedo, antes de contaminar o pipeline |
| Modelos internos (análise) | Pydantic v2 (mesmo que ingestão) | Consistência no codebase + `.model_dump()` nativo para serializar `PortfolioAnalysis` como JSON ao passar para o LLM no Stage 1. Alternativa seria `dataclass`, adequada para dados internos confiáveis, mas Pydantic vence pela facilidade de serialização |
| PDF | Jinja2 + WeasyPrint | Separa layout (HTML/CSS) de conteúdo; fácil incluir gráficos como base64 |
| Gráficos | matplotlib | Simples, sem dependência de servidor; imagem embutida no HTML como base64 |

---

## Saldo Disponível e Reserva de Liquidez

### Captura do saldo disponível

O TXT do portfólio do cliente inclui "Saldo Disponível" (ex: R$74.672,62 para Albert). Esse campo é extraído pelo LLM de ingestão e armazenado em `Portfolio.available_balance`. Ele alimenta um cálculo determinístico de **saldo investível** no `analyze_portfolio`.

### Regra de reserva de liquidez

Antes de recomendar qualquer aporte com o saldo disponível, o sistema calcula um colchão mínimo de liquidez proporcional ao patrimônio total do cliente. O objetivo é não recomendar investir o saldo inteiro — o cliente deve manter reserva acessível.

```
patrimônio_total = total_invested + available_balance
buffer = patrimônio_total × buffer_pct
saldo_investível = max(0, available_balance − buffer)
```

**Por que o percentual varia por tier e não pelo nome do perfil:**
O nome do perfil de risco (ex: "Moderado") é uma string livre vinda de um documento externo — a XP pode ter perfis com qualquer nome. Para evitar hardcodar nomes que podem mudar, o tier é inferido diretamente da `target_allocation`, que é um dado estruturado confiável:

| % equities-alvo (`acoes_pct + fundos_acoes_pct`) | Tier | Buffer |
|---|---|---|
| > 40% | Agressivo | 3% |
| 15–40% | Moderado | 5% |
| < 15% | Conservador | 10% |

**Exemplo — Albert (Moderado):** `acoes=20% + fundos_acoes=15% = 35%` → tier Moderado → buffer 5% × R$461k = R$23k → saldo investível = R$74k − R$23k = **R$51k**.

### Impacto nas recomendações

O sistema prioriza o saldo investível antes de sugerir realocações de posições existentes. A ordem é:
1. Usar o saldo disponível para fechar gaps de alocação (sem vender nada)
2. Só recomendar vendas/reduções se o saldo investível não for suficiente para fechar o gap prioritário

Isso muda o tom de "venda X e compre Y" para "use seu saldo disponível para aumentar Y — evitando evento de liquidez desnecessário."

---

## Fontes de Dados

| Dado | Fonte | Motivo |
|------|-------|--------|
| Portfólio, perfil de risco, análise macro | TXT fornecidos pela XP | Começar com TXT é mais simples; suporte a PDF é melhoria futura |
| Preços de ações (atual + mês anterior) | Yahoo Finance (`yfinance`) | Preço de ação na B3 é público e idêntico em qualquer fonte |
| Cotas de fundos (atual + mês anterior) | CVM — `inf_diario_fi_AAAAMM.csv` | CVM publica cotas diárias de todos os fundos registrados no Brasil |
| CNPJ dos fundos | CVM — `cad_fi.csv` | O portfólio tem o **nome** dos fundos, mas a API de cotas usa **CNPJ**. Precisamos fazer um "de-para" via fuzzy matching (rapidfuzz) |
| CDI mensal | BACEN API (série 12) | Benchmark de renda fixa. Usado para comparar se a carteira rendeu mais ou menos que o CDI no mês |
| IPCA mensal | BACEN API (série 433) | Dois usos: (1) calcular rendimento do CDB IPCA+5,45% do Albert; (2) verificar se a carteira está preservando poder de compra |
| Ibovespa mensal | Yahoo Finance (`^BVSP`) | Benchmark de ações. Usado para contextualizar a performance das ações e fundos de ações |
| Watchlist de ações para recomendações | `profitability_calc_wip.csv` | Contém 12 blue chips pagadoras de dividendos — 8 ausentes da carteira do Albert, candidatas a recomendação de compra |

### Por que cada fonte existe

**Yahoo Finance (ações e Ibovespa):** preço de ação na B3 é dado público — o mesmo em qualquer fonte. Yahoo Finance é gratuito, não exige cadastro, e tem histórico completo via `yfinance`.

**CVM `inf_diario_fi`:** fundos de investimento não têm "preço de ação" — têm **cota** (equivalente ao valor de uma fatia do fundo). Essa cota sobe ou desce conforme os ativos do fundo performam. A CVM (Comissão de Valores Mobiliários — o órgão regulador de investimentos no Brasil) publica esses valores diariamente para todos os fundos registrados. Para calcular retorno mensal de um fundo: `(cota_fim_do_mês - cota_fim_do_mês_anterior) / cota_fim_do_mês_anterior`.

**CVM `cad_fi`:** o portfólio do Albert lista fundos pelo nome (ex: "Riza Lotus Plus Advisory FIC FIRF REF DI CP"), mas a API de cotas identifica fundos pelo **CNPJ**. Esse arquivo é o cadastro de todos os fundos, com nome, CNPJ e a classe oficial CVM (`CLASSE`). Usamos fuzzy matching (rapidfuzz, score ≥ 75) para encontrar o CNPJ a partir do nome.

Além do CNPJ, extraímos o campo `CLASSE` (ex: `"Ações"`, `"Multimercado"`, `"Renda Fixa"`, `"Referenciado"`) — a **source of truth** para classificação do fundo em `classify_fund()`. O mapeamento completo está em `calculator.py → _CVM_CLASS_MAP`.

O arquivo `cad_fi.csv` é baixado **uma vez por processo** via `@lru_cache` em `_load_cvm_cad()` e compartilhado entre `lookup_fund_cnpj()` e `lookup_fund_class()` — sem download duplicado.

> **Limitação descoberta:** fundos com sufixo "Advisory" são veículos exclusivos da XP — FICs criados especificamente para a rede de assessores da XP e não registrados no cadastro público da CVM. Todos os fundos do Albert têm esse perfil. Nesses casos: (1) `lookup_fund_cnpj()` e `lookup_fund_class()` retornam `None`; (2) o retorno mensal fica `None` — o LLM usa o retorno acumulado desde a aplicação como contexto; (3) `classify_fund()` faz inferência por sufixo do nome como fallback (`FIA → fundos_acoes`, `FIRF → renda_fixa`, demais → `fundos_multimercado`). Em produção, a API interna da XP forneceria NAVs e classe de todos os fundos.

**BACEN série 12 (CDI):** o CDI é a taxa de juros interbancária diária — o principal benchmark de renda fixa no Brasil. A série 12 dá a taxa diária; compostas ao longo do mês, obtemos o CDI mensal. Serve de linha de corte: qualquer ativo de renda fixa que renda menos que o CDI no mês é um sinal de alerta.

**BACEN série 433 (IPCA):** a inflação mensal oficial. Usada de duas formas: (1) calcular quanto rendeu o CDB de Albert no mês — a taxa é IPCA+5,45%, então o retorno mensal é `(1 + IPCA_mensal) × (1 + 5,45%)^(1/12) - 1`; (2) verificar se o portfólio como um todo está acima da inflação (preservação de poder de compra).

> **Por que não usar o CSV para preços em vez da API?**
> Preços de ações são dados públicos idênticos em qualquer fonte. A API é mais escalável e sempre atualizada. O CSV seria um arquivo estático que envelheceria.

---

## Pipeline

| Decisão | Escolha | Motivo |
|---------|---------|--------|
| Ingestão dos TXTs | LLM com structured output (Pydantic) | Os arquivos são muito desformatados para parsing regex. LLM extrai dados corretamente mesmo com texto fora de ordem (ex: nome do fundo Ibiuna aparece após seus valores no TXT) |
| Cálculos financeiros | Python puro, zero LLM | LLMs cometem erros aritméticos. Todas as contas (retornos, gaps, flags) são determinísticas |
| Classificação de fundos | CVM `CLASSE` → fallback por nome | Source of truth: campo `CLASSE` do cadastro CVM. Fallback por sufixo do nome (`FIA`, `FIRF`, `FIM`) para fundos Advisory ausentes da CVM |
| Retorno ponderado da carteira | Calculado sobre ativos com dado disponível | Sem threshold mínimo de cobertura: se qualquer ativo tem retorno mensal, calcula. O label no PDF indica a cobertura ("Retorno (43% da carteira)") para ser transparente sem esconder o dado |
| Alocação-alvo por perfil | LLM extrai do documento de perfil | Não hardcodar por perfil — o sistema funciona com qualquer documento de perfil sem alteração de código |
| Recomendações | LLM com structured output | Garante que a saída seja sempre um JSON válido com campos bem definidos — auditável e escalável |
| Redação da carta | LLM separado | Responsabilidade única: só formata e escreve. Não analisa, não calcula |
| Saída em dois prompts | Análise → Redação | O LLM de análise trabalha com JSON preciso; o de redação recebe fatos já validados. Evita que o LLM misture análise e escrita criativa |
| Prompt do writer | Nunca mencionar limitação de dados | O LLM escreve como assessor XP com acesso completo. Fundos sem retorno mensal são tratados via retorno acumulado — sem expor ao cliente que o dado não veio de API pública |

---

## Recomendações

| Decisão | Escolha | Motivo |
|---------|---------|--------|
| Escopo das recomendações de venda/redução | Ativos da carteira atual com flags | Baseado em dados reais do cliente — confiável e acionável |
| Escopo das recomendações de compra | Teses e categorias — nunca tickers específicos | Decisão regulatória (ver abaixo) |
| Watchlist excluída do contexto do LLM | `exclude={"watchlist"}` no `model_dump()` | Sem possibilidade de recomendar tickers, a watchlist é ruído no prompt — removida |
| Sem recomendação de tickers inventados | N/A | LLM não deve inventar tickers — risco de alucinação em contexto financeiro é inaceitável |

### Trade-off: teses vs. tickers

**Decisão:** o LLM recomenda categorias e teses de investimento ("aumente exposição a renda fixa pós-fixada", "diversifique em fundos multimercado com menor correlação a ações"), nunca um ticker específico para compra.

**Por quê — regulatório:** no Brasil, recomendar um ativo de renda variável específico para compra é atividade de analista de valores mobiliários, regulada pela CVM e que exige certificação CNPI. Um sistema automatizado fazendo isso expõe a XP a risco regulatório real. Revisão de posições existentes (reduzir HAPV3, reduzir renda fixa) não se enquadra nessa restrição — é análise de carteira própria do cliente.

**O que parece perdido:** especificidade imediata — o cliente não sai da carta com um ticker na mão.

**Por que não é uma perda real:** a carta termina com uma call to action convidando o cliente para uma reunião com o assessor. Esse assessor — que tem a licença, o relacionamento e o contexto do dia — chega à reunião com a tese já preparada pelo sistema e faz o stock picking específico no momento certo. O produto **amplifica o assessor, não o substitui**. Um modelo que substituísse o assessor seria, além de regulatoriamente problemático, menos valioso como proposta de produto para a XP.

---

## Pendências

- [ ] Confirmar com XP quais perfis de risco existem e se há alocações-alvo oficiais (via WhatsApp — pendente)
- [ ] Suporte a PDF como input (melhoria futura, após MVP)

---

## O que faríamos com um mês completo

### Análise Macro — substituir PDF por APIs estruturadas

O relatório macro mensal da XP (`conteudos.xpi.com.br/brasil-macro-mensal/`) é fechado para clientes. Para produção, existem dois caminhos:

**Opção A — BCB Focus Report + scraping qualitativo:**
Para os números (IPCA, Selic, PIB, câmbio): API pública do Banco Central, atualizada semanalmente. Substitui completamente o parsing de PDF para a parte quantitativa.
Nota: para o MVP, os números já vêm do TXT da XP (já parsado) + BACEN API para dados realizados — o Focus só faria sentido para remover a dependência do PDF inteiramente.

**Opção B — Scraping autenticado do site da XP:**
Usando Playwright com sessão autenticada de assessor XP. Requer autorização explícita da XP (termos de uso). Preserva a análise qualitativa proprietária da equipe de research, que tem valor além dos números.

**Para o MVP atual:** usar o TXT fornecido — já temos o conteúdo necessário.

### Outras melhorias com prazo maior
- Alocações-alvo oficiais por perfil definidas pelo time de research da XP
- Integração direta com API interna da XP (elimina parsing de documentos)
- Envio automatizado do relatório por e-mail ou WhatsApp
- Histórico de patrimônio mês a mês para gráfico de evolução
- Suporte a múltiplos clientes em batch (processar N carteiras em paralelo)
