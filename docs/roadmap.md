# Roadmap Pós-POC

O que construiríamos com mais tempo, assumindo integração com os sistemas internos da XP.
Cada item tem justificativa de negócio — não são melhorias técnicas pelo bem da técnica.

---

## 1. Integrações com APIs Internas da XP

### 1.1 Portfólio e posições do cliente via API
**Hoje:** lemos um arquivo TXT exportado manualmente da plataforma XP.
**Com integração:** a API interna da XP forneceria o portfólio atualizado de qualquer cliente em tempo real, sem necessidade de exportação manual. O pipeline viraria um job que roda automaticamente no fechamento de cada mês para todos os clientes.
**Impacto:** escalabilidade real — de 1 cliente para 20.000+.

### 1.2 NAV (cota) dos fundos Advisory via API
**Hoje:** fundos Advisory da XP não constam no cadastro público da CVM. Usamos `return_since_inception_pct` como proxy — o LLM menciona o acumulado na carta, mas não há retorno mensal para incluir no gráfico de retornos nem no cálculo do retorno da carteira.
**Com integração:** a XP tem internamente os valores diários de cota de todos os seus fundos. Uma chamada de API substituiria o lookup na CVM.
**Impacto:** retorno mensal real para fundos — que representam ~67% da carteira do Albert e provavelmente de grande parte dos clientes middle market. Desbloquearia também: (a) retorno total da carteira calculado sobre 100% do patrimônio, (b) fundos aparecem no gráfico de retornos, (c) análise de volatilidade e sharpe por fundo.

**Análise disponível hoje mesmo sem dado mensal:**
- Retorno acumulado desde a aplicação (`return_since_inception_pct`) → mencionado na carta
- Valor investido vs. valor atual → P&L absoluto do fundo
- Classe do fundo (multimercado, FIA, renda fixa) → análise de alocação estratégica
- Comparação com CDI acumulado no período usando BACEN série 12

### 1.3 Lista de ativos recomendados pelo time de research
**Hoje:** usamos um CSV estático com 12 ações como watchlist de recomendações.
**Com integração:** o time de research da XP publica periodicamente listas de ativos recomendados por classe, setor e perfil de risco. Integrar essa lista tornaria as recomendações de compra baseadas em análise proprietária real.
**Impacto:** recomendações defensáveis, auditáveis e alinhadas com a visão da XP — direto no coração do objetivo de share of wallet.

### 1.4 Alocações-alvo oficiais por perfil de risco
**Hoje:** o LLM extrai uma alocação-alvo do documento de perfil de risco — é uma estimativa razoável, mas não é a política oficial da XP.
**Com integração:** a XP definiria as alocações-alvo por perfil (Conservador, Moderado, Arrojado) como parâmetros do sistema, gerenciados pelo time de produtos.
**Impacto:** recomendações de rebalanceamento padronizadas, governadas e auditáveis — requisito regulatório para escala.

### 1.5 Análise macro da XP via feed estruturado
**Hoje:** parseamos o PDF/TXT do relatório macro mensal com um LLM.
**Com integração:** o time de macro da XP publicaria as projeções em formato estruturado (JSON) via API interna, e o texto editorial seria consumido diretamente.
**Impacto:** elimina o parsing por LLM (ponto de falha), garante que os números no relatório ao cliente são os mesmos que a XP usa internamente.

---

## 2. Melhorias de Produto

### 2.1 Canal de entrega
**Hoje:** geramos um PDF localmente.
**Próximo passo:** envio automático por e-mail (SendGrid/AWS SES) ou WhatsApp Business API no fechamento de cada mês.
**Impacto direto no NPS:** o cliente recebe o relatório sem precisar acessar a plataforma — é o assessor chegando até ele, não o contrário.

### 2.2 Relatório interativo (além do PDF)
Um PDF é estático. Uma versão HTML interativa permitiria ao cliente clicar em cada ativo para ver mais detalhes, ajustar o horizonte temporal dos gráficos, ou entender melhor uma recomendação.

### 2.3 Personalização da linguagem por perfil do cliente
**Hoje:** o relatório usa um tom único para todos.
**Próximo passo:** ajustar vocabulário e profundidade técnica com base no histórico de interações do cliente com a plataforma XP (dado interno). Um cliente que nunca abriu o app merece linguagem diferente de um que acompanha o mercado diariamente.

### 2.4 Gráfico de evolução patrimonial
**Hoje:** só temos o snapshot atual da carteira — não conseguimos mostrar um gráfico de evolução do patrimônio mês a mês.
**Com integração:** a XP tem o histórico de posições de cada cliente. Um gráfico de linha mostrando patrimônio total mês a mês seria um terceiro gráfico no relatório PDF.
**Implementação planejada:** `src/report/charts.py` → `patrimony_evolution_chart(history: list[MonthlySnapshot])` usando `matplotlib` linha + área sombreada; o modelo `MonthlySnapshot(month: str, total_value: float)` viria de uma nova rota de API interna.
**Impacto:** o gráfico de evolução é o elemento mais emocional do relatório — ver o patrimônio crescendo mês a mês é o principal driver de NPS em wealth management.

---

## 3. Escalabilidade e Qualidade

### 3.1 Processamento em batch paralelo
**Hoje:** o pipeline processa um cliente por vez.
**Próximo passo:** processamento paralelo (asyncio + workers) para gerar os relatórios de todos os clientes do assessor simultaneamente no fechamento do mês.

### 3.2 Cache de dados de mercado
Dados como CDI, IPCA e Ibovespa são os mesmos para todos os clientes no mesmo mês. Buscar uma vez e reusar elimina chamadas redundantes às APIs externas.

### 3.3 Dashboard do assessor
O assessor precisa saber quais relatórios foram enviados, quais clientes têm os maiores desvios de alocação, quais estão com ativos problemáticos. Um dashboard simples transforma o sistema de "gerador de PDFs" em ferramenta de gestão de carteira.

### 3.4 Suporte a PDF como input
**Hoje:** só lemos TXT.
**Próximo passo:** adicionar parsing de PDF com `pdfplumber` ou `PyMuPDF` para os casos em que o TXT não está disponível. O LLM de ingestão já está estruturado para receber o texto — é só adicionar a extração.

### 3.5 Avaliação automática da qualidade do relatório
Antes de enviar ao cliente, um LLM avaliador (juiz) lê o relatório e verifica: os números batem com os dados calculados? As recomendações são consistentes com o perfil? Existe alguma afirmação sem respaldo? Isso garante qualidade em escala sem revisão humana de cada relatório.
