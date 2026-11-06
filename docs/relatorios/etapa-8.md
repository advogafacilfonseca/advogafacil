# Relatório da etapa 8: painel inicial e relatórios

Data: 06/11/2026. Os testes rodaram com PostgreSQL 16.15, Python 3.13 e PySide6 6.12 (modo offscreen), e também rodam no GitHub Actions a cada envio.

**Resultado: 139 testes automatizados no projeto inteiro, e os 139 passaram.**

## O que foi entregue

### Painel inicial

O painel abre com números reais do escritório e se atualiza sempre que volta à tela ou quando se clica em **Atualizar**.

- **Indicadores:** clientes ativos, processos em andamento, compromissos de hoje e atrasados.
- **Financeiro do mês:** recebido, despesas, saldo, total a receber, valor em atraso (com o número de parcelas) e parcelas que vencem em 7 dias.
- **Listas:** hoje, atrasados, próximas audiências (7 dias) e próximos prazos (7 dias). Dois cliques abrem o compromisso.
- Cada bloco aparece só para quem tem acesso à área. O servidor nem envia os outros blocos. **Sem a permissão Financeiro, nenhum valor aparece.**

### Relatórios

O menu **Relatórios** tem 10 relatórios:

| Relatório | Quem pode gerar | Período considerado |
| --- | --- | --- |
| Clientes | Acesso aos clientes | Início do atendimento (ou cadastro) |
| Processos | Acesso aos processos | Distribuição (ou cadastro) |
| Audiências | Agenda ou Pendências | Data da audiência |
| Prazos | Agenda ou Pendências | Vencimento do prazo |
| Pendências | Pendências ou Agenda | Compromissos não concluídos (parcelas só com Financeiro, sem valores) |
| Contratos | Contratos ou Financeiro | Início do contrato (**valores só com Financeiro**) |
| Parcelas | Financeiro | Vencimento |
| Recebimentos | Financeiro | Data do recebimento |
| Despesas | Financeiro | Data da despesa |
| Resultado financeiro | Financeiro | Mês a mês: recebido, despesas e saldo |

**Filtros:** período, responsável, cliente e situação. O resultado financeiro é do escritório inteiro, por isso usa só o período.

**Uso:** o relatório pode ser visto na tela com os totais e exportado em **PDF** ou **Excel**.

- O **PDF** sai em A4 deitado. Tem cabeçalho preto e dourado com o logotipo, data, hora e quem gerou, os filtros usados, os totais e o número das páginas.
- O **Excel** traz valores e datas como números e datas de verdade, então dá para somar e filtrar. Tem formato em R$, filtro nas colunas e cabeçalho fixo.
- Relatórios com valores levam a marca **"CONFIDENCIAL: contém informações financeiras"**.
- Cada exportação fica registrada na auditoria: quem exportou, qual relatório, formato, filtros e número de linhas. Os dados em si não são copiados para a auditoria.

## Regras de segurança

- O servidor monta o relatório e o arquivo já filtrados pelas permissões de quem pede. O que a pessoa não pode ver não chega a entrar no PDF ou no Excel.
- Pedir um relatório financeiro sem permissão é recusado no servidor em qualquer formato. A tentativa fica registrada na auditoria como acesso negado.
- A tela de Relatórios lista só os relatórios liberados para a pessoa.

## Regras verificadas por testes

| Regra | Resultado |
| --- | --- |
| Cada pessoa só vê e gera os relatórios da sua área | aprovado |
| Relatórios financeiros recusados sem permissão (tela, PDF e Excel), com registro na auditoria | aprovado |
| Contratos sem Financeiro: nenhuma coluna ou total com valores, inclusive no Excel | aprovado |
| Totais de parcelas (pago, em aberto, em atraso), recebimentos (estornos não somam) e despesas por categoria | aprovado |
| Resultado financeiro mês a mês e saldo líquido | aprovado |
| Filtros por período, responsável, cliente e situação; período invertido recusado | aprovado |
| Os 10 relatórios exportam em PDF e Excel, inclusive sem resultados | aprovado |
| Excel com valores numéricos em R$ e datas reais | aprovado |
| Painel com e sem Financeiro; blocos só das áreas liberadas | aprovado |
| Telas: painel, gerar relatório, filtrar, exportar PDF e Excel, cancelar a exportação | aprovado |

## Limite

Um relatório mostra no máximo 5.000 linhas. Se passar disso, ele avisa e pede para usar os filtros.
