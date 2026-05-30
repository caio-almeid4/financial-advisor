# XP AI Financial Advisor — Decisões Arquiteturais

## Visão Geral

Pipeline Python em 4 estágios que gera um relatório mensal personalizado para clientes XP, combinando análise determinística com LLM para parsing, análise e redação.

---

## Stack

- **Linguagem:** Python
- **LLM:** OpenAI API com structured outputs (Pydantic models / JSON mode)
- **Report:** Jinja2 (HTML template) → WeasyPrint (PDF)
- **Gráficos:** matplotlib, embutidos como base64 no HTML

---

## Fontes de Dados

| Dado | Fonte | Motivo |
|------|-------|--------|
| Portfólio, perfil de risco, análise macro | Arquivos TXT (versão simplificada dos PDFs fornecidos) | Começar com TXT é mais simples; adicionar suporte a PDF como melhoria futura |
| Preço atual e histórico das ações | brapi.dev ou Yahoo Finance | Preço de ação na B3 é o mesmo em qualquer fonte — API é mais limpa e escalável que arquivo estático |
| Cota dos fundos (mês atual e anterior) | API da CVM (`dados.cvm.gov.br`) | CVM publica cotas diárias de todos os fundos registrados no Brasil |
| CNPJ dos fundos | Cadastro CVM (`cad_fi.csv`) | Necessário para buscar cotas — o portfólio tem nomes, não CNPJs. Lookup por nome com fuzzy matching |
| IPCA mensal (para CDB) | API do Banco Central (série 13522) | Dado oficial para calcular rendimento do CDB IPCA+ |
| CDI mensal (benchmark renda fixa) | API do Banco Central (série 12) | Benchmark padrão de renda fixa no Brasil |
| Ibovespa mensal (benchmark ações) | Yahoo Finance (`^BVSP`) ou brapi.dev | Benchmark padrão da bolsa brasileira |

---

## Formato de Entrada

O pipeline recebe arquivos TXT como entrada. O contrato de entrada é um **JSON estruturado** produzido pelo Ingestion LLM — em produção, esse JSON viria da API interna da XP sem necessidade de parsing.

Schema do portfólio:
```json
{
  "cliente": {"nome": "Albert da Silva", "conta": "792854"},
  "acoes": [
    {"ticker": "LREN3", "quantidade": 1642, "preco_medio": 29.05},
    {"ticker": "MRFG3", "quantidade": 1504, "preco_medio": 7.15}
  ],
  "fundos": [
    {"nome": "Riza Lotus Plus Advisory FIC FIRF REF DI CP", "valor_aplicado": 83267.36, "valor_atual": 96178.73}
  ],
  "renda_fixa": [
    {"tipo": "CDB", "emissor": "Banco C6", "valor_aplicado": 30000, "valor_atual": 40478.75, "taxa": "IPCA+5.45%", "vencimento": "2024-09-05"}
  ]
}
```

---

## Pipeline Completo

```
TXT (portfólio)     ──┐
TXT (perfil risco)  ──┤── [Ingestion LLM] ──► JSON estruturado (validado com Pydantic)
TXT (macro)         ──┘         │
                                ▼
                        [Stage 0 — Python]
                    lookup CNPJ fundos na CVM
                    fetch preços ações (brapi/Yahoo)
                    fetch cotas fundos (CVM)
                    fetch CDI / Ibovespa / IPCA (BACEN / Yahoo)
                    extrair alocação-alvo do perfil (LLM structured)
                    calcular retornos mensais por ativo
                    calcular retorno total da carteira
                    calcular gaps vs. alocação-alvo
                    gerar flags determinísticas
                    output: JSON analítico completo
                                │
                                ▼
                        [Stage 1 — LLM structured output]
                    input: JSON analítico + excertos macro relevantes
                    output: observações + recomendações em JSON
                                │
                                ▼
                        [Stage 2 — LLM redação]
                    input: JSON de recomendações + nome/perfil do cliente
                    output: carta em português, tom humano
                                │
                                ▼
                    Jinja2 (HTML) + matplotlib (gráficos) → WeasyPrint → PDF
```

---

## Lógica de Recomendação

**Alocação-alvo:** Extraída do documento de perfil de risco via LLM structured output. Não hardcoded — funciona com qualquer perfil. Em produção, seria definida pelo time de research da XP.

**Flags determinísticas (Stage 0 — Python puro):**
```python
if ativo.retorno_total < -0.40:
    flags.append(f"{ativo.ticker} acumula {retorno:.0%} desde a compra")

if abs(gap_classe) > 0.10:
    flags.append(f"{classe} com gap de {gap:+.0%} vs. alocação ideal")

if ativo.retorno_mensal < cdi_mensal:
    flags.append(f"{ativo.ticker} rendeu abaixo do CDI no mês")
```

**Escopo das recomendações:**
- Rebalanceamento por classe de ativo (baseado nos gaps)
- Ativos específicos da carteira atual para rever (baseado nas flags)
- Sem recomendação de tickers novos — sem lista curada de research da XP, seria invenção

---

## Gráficos no Relatório

1. **Alocação atual vs. ideal:** barras agrupadas por classe de ativo
2. **Retorno mensal por ativo vs. CDI:** barras horizontais, linha de referência no CDI

Gerados com matplotlib, embutidos como imagens base64 no HTML antes da conversão para PDF.

---

## Conceitos Financeiros Importantes

**Rentabilidade: Janela Temporal**
O portfólio mostra "Rentabilidade (%)" que representa o retorno *desde o dia do investimento*, não do último mês. São janelas completamente diferentes e nunca devem ser misturadas no relatório. O sistema calcula e reporta ambas com rótulos explícitos.

**CDI:** Benchmark padrão de renda fixa brasileira. Se um ativo render menos que o CDI, o investidor teria se saído melhor em uma aplicação simples de renda fixa.

**Cota de fundo:** Equivalente ao preço de uma ação para fundos de investimento. Retorno mensal = (cota_atual - cota_mês_anterior) / cota_mês_anterior.

---

## Melhorias Futuras (fora do MVP de 7 dias)

- [ ] Suporte a PDF como input (além de TXT)
- [ ] Lista curada de ativos recomendados pela XP para recomendações de compra
- [ ] Alocações-alvo oficiais por perfil (a validar com XP via WhatsApp)
- [ ] Integração direta com API interna da XP (elimina parsing de documentos)

---

## Próximos Passos

- [ ] Ingestion: parsear TXT do portfólio → JSON (Pydantic)
- [ ] Ingestion: parsear TXT do perfil → alocação-alvo (LLM structured)
- [ ] Stage 0: lookup CNPJ fundos na CVM
- [ ] Stage 0: fetch preços, cotas e benchmarks via APIs
- [ ] Stage 0: calcular retornos e flags
- [ ] Stage 1: análise e recomendações (LLM structured output)
- [ ] Stage 2: redação da carta (LLM)
- [ ] Output: gráficos + Jinja2 + WeasyPrint → PDF
- [ ] Validar perfis de risco com XP (via WhatsApp — pendente)
