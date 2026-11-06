# Relatório — Etapa 3 (Clientes e pesquisa global)

Data: 06/11/2026. Ambiente de testes: PostgreSQL 16.15, Python 3.13, PySide6 6.12 (modo offscreen).
Testes também executados no GitHub Actions (Ubuntu) a cada envio.

**Resultado: 66 testes automatizados (projeto inteiro), 66 aprovados.**

## Entregue nesta etapa

- Seção **Clientes** (aparece só para quem tem a permissão "Clientes"): lista paginada com
  filtro Ativos / Atendimento encerrado / Todos e procura por nome, CPF ou telefone.
- **Cadastrar cliente**: nome completo (obrigatório), CPF, RG, nascimento, início do atendimento,
  dois telefones, e-mail, endereço completo, advogado responsável e observações.
- **Ficha do cliente** com as abas *Dados pessoais* e *Histórico* (quem fez o quê e quando,
  com o valor antes e depois de cada alteração). Botões Editar dados, Encerrar atendimento e
  Reativar.
- **Pesquisa global** no cabeçalho: começa com 3 caracteres, ignora acentos e maiúsculas,
  aceita nome e sobrenome juntos, CPF ou telefone (com ou sem pontuação), resultados
  paginados; dois cliques abrem a ficha.

## Regras verificadas por testes

| Regra | Resultado |
| --- | --- |
| CPF é conferido (dígitos verificadores) e não se repete entre clientes | aprovado |
| Mesmo nome sem CPF para diferenciar: o sistema pede confirmação antes de cadastrar | aprovado |
| Pesquisa com menos de 3 caracteres é recusada com aviso | aprovado |
| "Joã", "joao", "JOÃO" encontram "João"; os que começam com o termo vêm primeiro | aprovado |
| "joao silva" encontra só quem tem as duas palavras no nome | aprovado |
| Pesquisa por parte do CPF e do telefone, com ou sem pontuação | aprovado |
| Caracteres especiais (%, _, aspas) não quebram nem ampliam a pesquisa | aprovado |
| Sem a permissão "Clientes": menu oculto, API recusa (403) e pesquisa global não mostra clientes | aprovado |
| Duas pessoas editando o mesmo cliente: a segunda é avisada e nada é sobrescrito | aprovado |
| Quatro gravações simultâneas na mesma versão: só uma é aceita | aprovado |
| Encerrar preserva o cadastro e o histórico; o banco recusa apagar clientes | aprovado |
| Todas as ações em clientes ficam na auditoria | aprovado |

## O que fica para as próximas etapas

- Os dados de **contrato e financeiro** do cliente (valor, parcelas, pagamentos) entram na
  etapa 5, junto com o módulo financeiro protegido.
- As abas de **Processos, Agenda e Documentos** na ficha entram nas etapas 4 e 6.
- A pesquisa global passará a incluir processos (número CNJ) na etapa 4.
