# Relatório da etapa 9: Central de Backups

Data: 06/11/2026. Os testes rodaram com PostgreSQL 16.15, Python 3.13 e PySide6 6.12 (modo offscreen), e também rodam no GitHub Actions a cada envio.

**Resultado: 149 testes automatizados no projeto inteiro, e os 149 passaram.** Os testes fazem backups e restaurações de verdade, com `pg_dump` e `pg_restore` num PostgreSQL real.

## O que foi entregue

O menu **Central de Backups** é só da Master. As cópias saem do banco de dados e dos documentos (inclusive os comprovantes do financeiro) e vão para o HD externo.

| Requisito | Como ficou |
| --- | --- |
| Backup incremental ou equivalente | **Backup rápido** a cada N horas (padrão 4). Copia o banco inteiro e só os documentos novos. Cada versão é um ponto completo de restauração. |
| Backup completo diário | No horário escolhido (padrão 23:00). Confere de novo todos os documentos, no HD e no servidor. |
| Histórico de versões | Pastas por data, com retenção configurável (padrão 60 dias). As 3 últimas versões completas nunca são apagadas. |
| Destino em HD externo | Pasta escolhida pela Master, com o botão "Verificar" (como o servidor enxerga a pasta). |
| Cópia criptografada em outro local | Arquivo `.afbk` (AES-256-GCM, chave derivada da senha por scrypt), gravado e depois aberto e conferido por inteiro. A senha não é guardada. |
| Verificação de integridade | Impressão digital SHA-256 do banco e de cada arquivo, lida de volta depois de gravada. O banco é validado com `pg_restore --list`. |
| Registro de data e resultado | Histórico de cada execução: tipo, origem, quem pediu, duração, tamanho, arquivos novos e mensagem. Não pode ser apagado. |
| Alertas de falha | Aviso para a Master no aplicativo e por e-mail (se a conta de envio estiver conectada). |
| HD desconectado ou sem espaço | Detectado antes de começar, com mensagem clara e aviso diário enquanto o HD estiver desconectado. |
| Restauração em outro computador | Comando `restaurar` no programa do servidor. Aceita a pasta do HD ou a cópia criptografada (pede a senha). |
| Procedimento documentado | `docs/manuais/recuperacao-de-dados.md` cobre falha, roubo, corrupção e defeito do servidor. |
| Teste periódico da restauração | Automático a cada 7 dias (configurável) e pelo botão "Testar restauração agora". Restaura num banco temporário, confere as contagens e apaga o banco temporário. |

## Detalhes de segurança

- **Banco consistente:** o banco é exportado num instantâneo do PostgreSQL. As contagens e a lista de documentos do manifesto são lidas no mesmo instante do `pg_dump`.
- **Arquivo danificado no servidor:** o backup completo detecta o problema (o hash não confere com o registrado no envio) e **mantém a cópia boa** no HD.
- **Restauração protegida:** ela confere tudo antes de começar e só grava num banco vazio ou recém-instalado. Um banco com dados nunca é apagado.
- **Sem segredos no backup:** a autorização do Google, a senha da cópia e a chave do servidor não vão para o backup. Depois de restaurar em outro computador, a Master conecta a conta de envio de novo e redefine a senha da cópia.
- **Um backup por vez:** uma trava no banco impede dois backups simultâneos.
- **Avisos de backup:** só a Master recebe.

## Regras verificadas por testes

| Regra | Resultado |
| --- | --- |
| Backup completo real com manifesto, documentos e comprovantes conferidos | aprovado |
| Backup rápido copia só o que é novo | aprovado |
| Teste de restauração em banco temporário (apagado no fim) | aprovado |
| Documento corrompido no servidor: detectado, cópia boa mantida, Master avisada | aprovado |
| HD desconectado e falta de espaço: falha clara, alerta sem duplicar, só para a Master | aprovado |
| Cópia criptografada: conteúdo ilegível sem senha; senha errada, arquivo alterado e arquivo cortado recusados | aprovado |
| Restauração em "outro computador" a partir da cópia criptografada: a Master entra e abre o documento | aprovado |
| Restauração a partir do HD num servidor recém-instalado; backup danificado é recusado antes de começar | aprovado |
| Banco com dados nunca é sobrescrito | aprovado |
| Retenção: apaga só as versões antigas do sistema e mantém as 3 últimas completas | aprovado |
| Agendamento: completo diário, rápido por intervalo, teste periódico, nova tentativa após falha | aprovado |
| Somente a Master acessa; caminhos relativos recusados; auditoria das ações | aprovado |
| Tela: configurar, verificar pasta, definir senha, fazer backup e testar restauração | aprovado |

Também conferi à mão que a restauração funciona com o usuário do banco sem privilégios de administrador, como na instalação do Windows.

## Observações para a instalação real

- O serviço do servidor roda como conta do sistema. Por isso enxerga HDs USB ligados no próprio servidor. Para pasta de rede, use o caminho completo (`\\computador\pasta`) e dê permissão de gravação ao computador servidor.
- Recomendo proteger o HD externo com o BitLocker To Go (orientação no guia).
