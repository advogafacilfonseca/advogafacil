# Relatório — Etapa 1 (Fundação)

Data: 06/11/2026. Ambiente de testes: PostgreSQL 16.15, Python 3.13, PySide6 6.12 (modo offscreen).

**Resultado: 30 testes automatizados, 30 aprovados.**

## O que foi testado

| Área | Testes |
| --- | --- |
| Criação da Master | código de instalação válido/ inválido; código de uso único apagado do banco e do disco; segunda Master recusada; 5 tentativas simultâneas geram uma única Master; validações em português |
| Proteções no banco | inserir Master fora do assistente; promover usuário comum a Master; desativar ou apagar a Master; segunda Master mesmo com autorização; alterar ou apagar auditoria — todas recusadas pelo PostgreSQL |
| Senhas | hash Argon2id; senha nunca armazenada em texto |
| Login e sessões | login correto; mesma mensagem para senha errada e usuário inexistente; bloqueio após tentativas; token guardado só como hash; expiração por inatividade e por tempo máximo; logout invalida o token; troca de senha encerra outras sessões |
| Permissões | usuário recebe só as permissões concedidas; cargo/nome "Master" não dá poder; rota financeira bloqueada sem permissão (e registrada na auditoria); rota exclusiva da Master bloqueada mesmo com todas as permissões; usuário desativado perde a sessão |
| Aplicativo | conexão com servidor real; aviso claro com servidor desligado; assistente da Master (erro e sucesso); login errado e certo; janela principal com status do servidor; sair encerra a sessão |
| Empacotamento | servidor empacotado com PyInstaller sobe, cria o banco e responde; aplicativo empacotado abre e conecta ao servidor (teste em Linux; o build Windows roda no GitHub Actions) |

## Ainda não verificado nesta etapa

- Instaladores `.exe` e serviços do Windows: dependem do build em Windows (GitHub Actions).
- HTTPS entre computadores: previsto para a etapa 2. Até lá, usar apenas em ambiente de testes.
