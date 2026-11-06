# Relatório — Etapa 5 (Contratos e financeiro)

Data: 06/11/2026. Ambiente de testes: PostgreSQL 16.15, Python 3.13, PySide6 6.12 (modo offscreen).
Testes também executados no GitHub Actions (Ubuntu) a cada envio.

**Resultado: 105 testes automatizados (projeto inteiro), 105 aprovados.**

## Entregue nesta etapa

- Seção **Contratos** (permissão "Contratos" ou "Financeiro") e seção **Financeiro**
  (somente com a permissão "Financeiro").
- **Cadastro de contrato** com cliente, processo (opcional), serviço contratado, advogado
  responsável, início do atendimento, valor total, entrada e seu vencimento, quantidade de
  parcelas, valor de cada parcela (ou divisão automática), primeiro vencimento, dia dos
  vencimentos seguintes e observações. A tela mostra a prévia das parcelas antes de salvar.
- **Parcelas personalizadas**: valores e vencimentos diferentes, digitados na própria prévia.
  O sistema confere se entrada + parcelas = valor total e explica a diferença quando não fecha.
- **Ficha do contrato** com os totais (contratado, recebido, a receber, em atraso, cancelado)
  e as abas Dados do contrato, Parcelas, Recebimentos e Histórico.
- **Registrar recebimento**: valor (já preenchido com o restante), data, forma de pagamento
  (Pix, dinheiro, transferência, boleto, cartão de crédito/débito, cheque, outro),
  observações e comprovante opcional. Recebimento parcial mantém a parcela em aberto com o
  restante; ao completar o valor, a parcela vira "Paga" e, quitadas todas, o contrato vira
  "Quitado".
- **Estorno de recebimento** com motivo: o lançamento continua visível como "ESTORNADO".
- **Cancelar parcela**, **cancelar contrato** e **renegociar parcelas** (escolhe as parcelas em
  aberto, informa o novo valor total, a quantidade e os vencimentos), sempre com motivo.
- **Financeiro**: resumo por período (total contratado, recebido, a receber, em atraso,
  recebido e previsto no período, despesas e saldo líquido), avisos de vencimento, lista de
  parcelas com filtros (em aberto, vencidas, a vencer, pagas, todas), recebimentos do período.
- **Outras despesas**: combustível, estacionamento, alimentação, transporte, materiais,
  despesas administrativas, custas e outras; com valor, data, responsável, cliente/processo
  relacionado (opcional), observações e comprovante. Editar e cancelar ficam no histórico.
- **Ficha do cliente** ganhou a aba "Contratos e financeiro" ("Contratos" para quem não tem o
  financeiro).

## Contrato assinado não é dinheiro recebido

O valor do contrato e as parcelas entram como **a receber**. Só passa a contar como
**recebido** o que for registrado em "Registrar recebimento". A conta sempre fecha:
contratado = recebido + a receber + cancelado (conferido nos testes, inclusive após
renegociação e cancelamento).

## Nada é apagado

Contratos, parcelas, recebimentos, despesas e comprovantes não podem ser apagados (o banco
de dados impede, mesmo fora do sistema). Correções são feitas por estorno, cancelamento ou
renegociação, sempre com motivo, usuário, data e hora na auditoria.

## Sigilo do financeiro

- Sem a permissão "Financeiro", o servidor **não envia** valores, parcelas, recebimentos,
  despesas, resumo nem comprovantes, mesmo que alguém tente acessar a API diretamente.
- Quem tem só "Contratos" vê e edita os dados do serviço contratado (cliente, processo,
  responsável, observações), sem nenhum valor. O histórico do contrato também esconde os
  lançamentos financeiros para essa pessoa.
- Cadastrar um contrato exige "Contratos" **e** "Financeiro", porque o cadastro gera as
  parcelas (valores).

## Regras verificadas por testes

| Regra | Resultado |
| --- | --- |
| Exemplo do pedido: R$ 6.000, entrada de R$ 1.000 e 5 parcelas de R$ 1.000 | aprovado |
| Divisão automática sem perder centavos (333,33 + 333,33 + 333,34) | aprovado |
| Vencimento no dia 31 cai no último dia dos meses curtos (31/01 → 28/02 → 31/03) | aprovado |
| Parcelas que não somam o valor total são recusadas com explicação | aprovado |
| Recebimento parcial, total e quitação automática do contrato | aprovado |
| Dois recebimentos ao mesmo tempo não ultrapassam o valor da parcela | aprovado |
| Reenvio do mesmo recebimento após queda de conexão não duplica | aprovado |
| Estorno preserva o lançamento; recebimentos não podem ser alterados nem apagados | aprovado |
| Cancelar parcela e contrato mantém o que já foi recebido | aprovado |
| Renegociação substitui o restante das parcelas escolhidas e mantém a conta fechada | aprovado |
| Sem "Financeiro": nenhum valor na API, nas telas, no histórico e nos comprovantes | aprovado |
| Despesas: lançar, editar, cancelar com motivo; resumo por categoria e saldo do período | aprovado |
| Avisos "AMANHÃ TEM PAGAMENTO", "PAGAMENTO VENCE HOJE" e "PARCELA ATRASADA HÁ N DIAS" | aprovado |
| Telas: cadastro com prévia, parcelas personalizadas, ficha, recebimento com comprovante, estorno, cancelamentos, renegociação, despesas | aprovado |

## Observação técnica

Em cerca de 2 de 15 execuções completas dos testes neste ambiente, o processo de testes
encerrou de forma inesperada (falha interna, sem teste reprovado). Não se repetiu em 7
execuções seguidas. O GitHub Actions registra o detalhe técnico automaticamente se acontecer
lá; a causa será fechada antes dos testes reais no Windows (etapa 11).

## O que fica para as próximas etapas

- Os avisos de vencimento passarão a aparecer na Central de Pendências e no painel inicial
  (etapas 6 e 8) e a ser enviados por e-mail (etapa 7).
- Relatórios financeiros em PDF e Excel entram na etapa 8.
- Comprovantes entram nas cópias de segurança automáticas da etapa 9.
