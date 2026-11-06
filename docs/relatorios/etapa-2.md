# Relatório — Etapa 2 (Usuários, permissões, auditoria e HTTPS)

Data: 06/11/2026. Ambiente de testes: PostgreSQL 16.15, Python 3.13, PySide6 6.12 (modo offscreen).

**Resultado: 47 testes automatizados (projeto inteiro), 47 aprovados.**

## Entregue nesta etapa

- Tela **Usuários e Permissões**: cadastrar com senha provisória, editar nome/cargo/e-mail,
  conceder e retirar as 10 permissões, desativar/reativar, redefinir senha.
- **Senha provisória**: o usuário só consegue trocar a senha até criar a sua (bloqueio no servidor).
- **Auditoria** consultável pela Master, com filtros por período, usuário e tipo de ação.
- **HTTPS** com certificado próprio do servidor. O app registra o certificado na primeira
  conexão (mostrando a impressão digital para conferência) e passa a recusar qualquer outro.
- **Sem gravação duplicada**: cada gravação leva uma chave única; se a conexão cair antes da
  resposta, o app reenvia e o servidor devolve o resultado original sem gravar de novo.

## Regras verificadas por testes

| Regra | Resultado |
| --- | --- |
| Somente a Master concede, altera ou retira permissões (inclusive na criação) | aprovado |
| Ninguém altera os próprios privilégios | aprovado |
| Usuário com "Administração de usuários" não altera a Master nem outro administrador | aprovado |
| Cargo "Advogada Master" não concede poder algum | aprovado |
| Desativar encerra sessões na hora e preserva o histórico; reativar devolve o acesso | aprovado |
| Master não pode ser desativada nem ter permissões alteradas | aprovado |
| Redefinir senha encerra sessões e exige nova troca | aprovado |
| Mesma chave de operação não duplica cadastro (API e app com queda simulada) | aprovado |
| Auditoria visível só para a Master | aprovado |
| Certificado diferente do registrado é recusado pelo app | aprovado |
| Fluxo pela interface: cadastro, permissões, troca obrigatória, auditoria | aprovado |
