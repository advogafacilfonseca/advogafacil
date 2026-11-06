# Relatório — Etapa 7 (Notificações e e-mail)

Data: 06/11/2026. Ambiente de testes: PostgreSQL 16.15, Python 3.13, PySide6 6.12 (modo offscreen).
Testes também executados no GitHub Actions (Ubuntu) a cada envio.

**Resultado: 132 testes automatizados (projeto inteiro), 132 aprovados.**

## Entregue nesta etapa

- **Serviço de avisos no servidor**: roda em segundo plano dentro do servidor e funciona
  mesmo com todos os aplicativos fechados. A cada 5 minutos gera os avisos novos e envia os
  e-mails pendentes. Se houver mais de um processo, uma trava no banco garante um ciclo por vez.
- **Categorias de aviso**: audiências, reuniões, prazos, ligações e retornos pendentes,
  outros compromissos, compromissos atrasados e avisos financeiros (AMANHÃ TEM PAGAMENTO,
  PAGAMENTO VENCE HOJE, PARCELA ATRASADA).
- **A Master escolhe quem recebe cada categoria** (menu Notificações → Quem recebe), podendo
  avisar várias pessoas, não só o responsável, e marcar "avisar também o responsável".
- **Botão "Avisos" no cabeçalho** de cada pessoa, com o número de não lidos. Dois cliques
  abrem o compromisso ou o contrato relacionado.
- **Conta oficial de envio** (menu Notificações → Conta de envio): conexão com Gmail ou Google
  Workspace por OAuth 2.0, teste de envio e desconexão. Manual passo a passo em
  `docs/manuais/configurar-envio-google.md`.
- **Histórico de envios** com filtros e a situação de cada e-mail: enviado, aguardando, falhou
  (após novas tentativas), rejeitado, não configurado, desligado, sem e-mail, ou "deixou de
  valer". A Master pode reenviar os que falharam.
- Horário de início dos avisos do dia (padrão 07:00) e opção de desligar o envio por e-mail
  sem desligar os avisos no aplicativo.

## Regras de segurança

- Só recebe quem tem a permissão **"Recebimento de notificações"** e acesso à área do aviso
  (Agenda ou Pendências). **Avisos financeiros exigem a permissão Financeiro.** A regra vale na
  configuração e de novo na hora do envio; se a pessoa perder a permissão, deixa de receber e
  de ver os avisos financeiros antigos.
- Os avisos **não mostram valores em reais** (nem no aplicativo nem no e-mail).
- A conta Google é autorizada na tela do próprio Google: **o sistema nunca vê a senha**, pede
  só a permissão de enviar (não lê a caixa de entrada), e os destinatários não precisam
  informar senha nenhuma.
- A autorização fica no banco **criptografada** com uma chave que existe só no servidor. Numa
  migração de servidor, a conta precisa ser conectada de novo (a autorização não viaja junto).
- O histórico de avisos e envios não pode ser apagado (o banco impede).

## Sem duplicidade e com interrupção automática

- Cada aviso tem uma chave única por pessoa: rodar o serviço várias vezes não repete avisos.
- Antes de enviar, o serviço confere se o aviso ainda vale: parcela paga, compromisso
  concluído, cancelado ou reagendado → o e-mail não é enviado e o histórico registra o motivo.
- Falha temporária (internet, Google ocupado): novas tentativas em 5, 10, 20 e 40 minutos;
  depois disso fica "Falhou". Recusa definitiva (endereço inválido, autorização revogada):
  "Rejeitado", com o motivo.

## Regras verificadas por testes

| Regra | Resultado |
| --- | --- |
| Só a Master configura; quem não tem a permissão de notificações ou o Financeiro é recusado | aprovado |
| Aviso para todos os escolhidos e para o responsável; nada é repetido em novos ciclos | aprovado |
| Avisos no aplicativo: não lidos, marcar como lido, abrir o item relacionado | aprovado |
| Reagendar ou concluir interrompe o e-mail ainda não enviado | aprovado |
| Parcela paga: os avisos daquela parcela param | aprovado |
| E-mail financeiro sem valores; pessoa sem Financeiro não recebe nem vê | aprovado |
| Novas tentativas com intervalo crescente, "Falhou" após 5, "Rejeitado" sem repetir, reenvio manual | aprovado |
| Horário de início e envio por e-mail desligado | aprovado |
| Histórico não pode ser apagado | aprovado |
| Conexão Google: endereço de retorno só local, PKCE, código usado uma única vez, segredos criptografados | aprovado |
| Teste de envio, falhas do Google (indisponível, recusa, autorização revogada) | aprovado |
| Servidor sem a chave (migração) exige nova conexão | aprovado |
| Telas: quem recebe, conta de envio (conectar e testar), histórico, botão Avisos | aprovado |

Os testes simulam o Google. O envio real será conferido quando a conta oficial for conectada.

## Pendente com a Flavia

- Confirmar a conta de envio (cartão no projeto). A conexão Google já está pronta; se a escolha
  for outro serviço (Brevo ou e-mail do domínio), adiciono esse tipo de conta.
- Criar o identificador no Google Cloud (manual) e conectar pela tela.
