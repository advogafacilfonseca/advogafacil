# Relatório — Etapa 6 (Agenda e Central de Pendências)

Data: 06/11/2026. Ambiente de testes: PostgreSQL 16.15, Python 3.13, PySide6 6.12 (modo offscreen).
Testes também executados no GitHub Actions (Ubuntu) a cada envio.

**Resultado: 118 testes automatizados (projeto inteiro), 118 aprovados.**

## Entregue nesta etapa

- Seção **Agenda** (permissão "Agenda") com visualização **diária, semanal e mensal**, botões
  ◀ Hoje ▶, filtros por responsável e tipo, e opção de mostrar cancelados. Clicar no dia (na
  semana ou no mês) abre a visão diária.
- Tipos de compromisso: audiência, reunião, ligação, retorno a cliente, consulta, diligência,
  entrega de documentos, prazo, tarefa e outro.
- Cada compromisso tem título, tipo, cliente, processo (quando houver), responsável, data,
  horário (ou "dia todo"), duração, local, prioridade (baixa, normal, alta, urgente),
  observações e situação (agendado, concluído, cancelado; "atrasado" quando passou da hora).
- **Criar, editar, reagendar, atribuir, concluir e cancelar**, com histórico completo
  (quem fez, quando, de que data para qual, motivo).
- **Avisos** no topo da agenda: "HOJE TEM AUDIÊNCIA", "AMANHÃ TEM AUDIÊNCIA", "HOJE TEM
  REUNIÃO", "AMANHÃ TEM REUNIÃO", "VOCÊ TEM UMA LIGAÇÃO PENDENTE", "EXISTE UM RETORNO DE CLIENTE
  PENDENTE", "PRAZO VENCE HOJE/AMANHÃ" e "ATRASADO: ...".
- **Central de Pendências** (permissão "Pendências"): audiências próximas, prazos, ligações,
  retornos, reuniões, entregas, tarefas atrasadas e compromissos não concluídos, de todo o
  escritório. Contadores (atrasados, hoje, amanhã, próximos dias) e filtros por responsável
  (inclusive "sem responsável"), cliente, processo, tipo, prioridade, situação e período.
  Na própria central é possível concluir, reagendar e atribuir.
- **Integração com processos**: a "próxima audiência ou prazo" informada no cadastro do
  processo vira automaticamente um compromisso na agenda. Mudar a data no processo reagenda o
  compromisso; reagendar na agenda atualiza o processo; concluir ou cancelar na agenda libera o
  campo no processo; retirar a data do processo cancela o compromisso (com o motivo registrado).

## Permissões

| Quem tem | Pode |
| --- | --- |
| Agenda | ver a agenda, criar, editar, reagendar, atribuir, concluir e cancelar |
| Pendências | ver a Central de Pendências, concluir, reagendar e atribuir (não cria nem cancela) |
| Pendências + Financeiro | também vê as parcelas vencidas e a vencer na central e registra o recebimento |

Sem a permissão Financeiro, a central não mostra parcelas, valores nem o filtro de financeiro,
e o servidor também não envia esses dados.

## Regras verificadas por testes

| Regra | Resultado |
| --- | --- |
| Título e tipo obrigatórios; horário inválido é recusado com explicação | aprovado |
| Edição simultânea: a segunda pessoa é avisada, nada é sobrescrito | aprovado |
| Reagendar exige data diferente; conta os reagendamentos e guarda o motivo | aprovado |
| Concluído ou cancelado não pode mais ser alterado | aprovado |
| Cancelar exige motivo; compromissos não podem ser apagados (o banco impede) | aprovado |
| Visões de dia, semana e mês trazem os compromissos certos; filtros por tipo, responsável, cliente, prioridade e texto | aprovado |
| Prazo de "dia todo" fica no dia certo, sem horário | aprovado |
| Todos os avisos da lista acima aparecem no dia certo; "somente os meus" filtra pelo responsável | aprovado |
| Próxima audiência/prazo do processo ↔ compromisso, nos dois sentidos | aprovado |
| Permissões: Agenda e Pendências separadas; sem nenhuma das duas, acesso negado | aprovado |
| Central: grupos, ordem por urgência, todos os filtros, concluídos e cancelados | aprovado |
| Central sem Financeiro: nenhuma parcela, valor ou filtro financeiro | aprovado |
| Telas: agendar, prazo de dia todo, visões, ficha com reagendar/atribuir/concluir/cancelar, central | aprovado |

## O que fica para a próxima etapa (7)

O pedido inclui que a Master escolha quais usuários recebem cada categoria de aviso, que os
avisos sejam enviados por e-mail mesmo com o aplicativo fechado (serviço no servidor), sem
duplicidade e com registro do resultado. Isso é a etapa 7. Nesta etapa os avisos aparecem
dentro do aplicativo, para todos com acesso à agenda.
