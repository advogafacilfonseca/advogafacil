# Advoga Fácil

Sistema desktop para escritório de advocacia (Windows 10/11), multiusuário, com servidor central.

- **Aplicativo desktop:** Python + PySide6 (`desktop/advoga_desktop`)
- **Servidor/API:** Python + FastAPI (`server/advoga_server`)
- **Banco central:** PostgreSQL 16, SQLAlchemy 2 e Alembic
- **Código compartilhado:** contratos de dados e permissões (`shared/advoga_shared`)
- **Instaladores:** PyInstaller + Inno Setup (`installer/`), gerados no Windows pelo GitHub Actions
- **Acesso remoto:** Tailscale (sem portas abertas na internet)

O código fica separado dos dados. No servidor, banco, documentos, configurações e backups
ficam em `C:\ProgramData\AdvogaFacil`. Atualizar ou reinstalar o programa não apaga dados.

## Estado atual

Etapas 1 a 9 concluídas: fundação, usuários e permissões, clientes, processos e documentos,
contratos e financeiro, agenda e Central de Pendências, notificações por e-mail, painel e
relatórios (PDF e Excel) e Central de Backups. Veja `docs/relatorios/` e `docs/manuais/`.

## Desenvolvimento

```bash
python -m venv .venv && . .venv/bin/activate        # no Windows: .venv\Scripts\activate
pip install -e ".[servidor,desktop,dev]"

# Testes (usam um PostgreSQL real; cada execução cria e apaga um banco temporário)
export ADVOGA_TESTE_PG_ADMIN=postgresql+psycopg://postgres@127.0.0.1:5432/postgres
python -m pytest

# Servidor local de desenvolvimento
export ADVOGA_DATABASE_URL=postgresql+psycopg://usuario:senha@127.0.0.1:5432/advoga
export ADVOGA_PASTA_DADOS=./dados-dev
advoga-servidor servir          # mostra o código de instalação para criar a Master

# Aplicativo
advoga-facil
```

## Estrutura

```
shared/advoga_shared/     contratos de dados e lista de permissões
server/advoga_server/     API, regras, modelos, migrações (alembic/)
desktop/advoga_desktop/   aplicativo: tema, telas, assistente, cliente da API
installer/                PyInstaller, Inno Setup, scripts do servidor Windows, ícones
docs/                     manuais e relatórios
tests/                    testes do servidor (PostgreSQL real) e do aplicativo
```
