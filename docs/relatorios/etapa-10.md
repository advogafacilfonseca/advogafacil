# Relatório da etapa 10: assistente de migração do servidor

Data: 06/11/2026. Os testes rodaram com PostgreSQL 16, Python 3.13 e PySide6 (modo offscreen), e também rodam no GitHub Actions a cada envio.

**Resultado: 156 testes automatizados no projeto inteiro, e os 156 passaram.** Os testes da migração usam dois bancos PostgreSQL reais e duas pastas de dados, como se fossem dois computadores.

## O que foi entregue

O menu **Migração de servidor** (só a Master) no servidor antigo e a opção **Importar dados de outro servidor** na primeira abertura do aplicativo no servidor novo. O passo a passo para a Master está em `docs/manuais/migracao-de-servidor.md`.

| Requisito | Como ficou |
| --- | --- |
| Exportar o banco completo | `pg_dump` com as tabelas travadas para gravação: as gravações em andamento terminam antes e nenhuma alteração fica para trás. |
| Exportar documentos e anexos | Todos os documentos e comprovantes do financeiro, conferidos pelo SHA-256 antes de entrar no pacote. Um arquivo danificado no servidor impede a exportação, com mensagem clara. |
| Usuários e permissões | Mesmos usuários, senhas e permissões. A Master continua Master. |
| Clientes e processos | Preservados, com movimentações e documentos vinculados. |
| Contratos, parcelas e pagamentos | Preservados, com os comprovantes. Os totais do contrato são idênticos. |
| Agenda e pendências | Preservadas. |
| Configurações e histórico | Configurações, auditoria, avisos e históricos de backups e migrações preservados. |
| Importar no novo PostgreSQL | Só num servidor recém-instalado, sem a conta Master, autorizado pelo código de instalação do servidor novo. |
| Verificar a integridade | Cada tabela é conferida pelo número de registros **e** por uma impressão digital (MD5) do conteúdo. Cada documento é conferido pelo SHA-256, e a lista de documentos do banco precisa bater com a do pacote. |
| Relatório de sucesso ou erro | Na tela, tabela por tabela, com o código de confirmação e o que falta fazer. Também em arquivo no servidor novo e em PDF pelo histórico. Em caso de erro, a mensagem diz o que falhou. |
| Sem recadastro | Ninguém precisa recadastrar nada. Todos entram com as mesmas senhas. |
| Credenciais e tokens | O pacote é criptografado (AES-256-GCM, chave derivada da senha por scrypt). A autorização do Google e a senha da cópia dos backups **não** são transferidas: a Master as configura de novo no servidor novo. As sessões abertas são encerradas. |
| Impedir duas bases oficiais | (1) Servidor antigo em **somente leitura** desde a exportação. (2) **Desativação definitiva** do antigo com o código de confirmação que só o servidor novo gera. (3) Os computadores do escritório guardam a identidade do servidor oficial e **recusam o servidor antigo** depois de conectar ao novo. (4) Servidor em migração ou desativado não faz backups nem envia avisos. |

## Etapas da importação

1. Abre o pacote com a senha e confere cada arquivo.
2. Confere se o pacote veio de uma versão compatível do sistema.
3. Prepara o banco novo (recusa um banco que já tenha dados).
4. Importa o banco e confere cada tabela.
5. Copia e confere cada documento e comprovante.
6. Atualiza a estrutura do banco, se o servidor novo for de versão mais nova.
7. Dá ao servidor novo uma identidade nova, ligada à do antigo, e remove os segredos que não devem viajar.

Se qualquer etapa falhar, o banco novo volta a ficar vazio, com o mesmo código de instalação, e a importação pode ser repetida.

## Regras verificadas por testes

| Regra | Resultado |
| --- | --- |
| Migração completa para "outro computador": usuários, senhas, permissões, clientes, processo, documento, contrato, parcelas, pagamento com comprovante, agenda e pendência, configurações e auditoria | aprovado |
| Contagem de cada tabela idêntica e conteúdo conferido; totais do contrato iguais | aprovado |
| Pacote ilegível sem a senha; senha errada recusada sem gravar nada | aprovado |
| Servidor antigo em somente leitura durante a migração (consulta e login funcionam) | aprovado |
| Código de instalação errado, pacote inexistente e servidor já configurado: recusados | aprovado |
| Conta Google e senha da cópia não transferidas; sessões antigas não valem no servidor novo | aprovado |
| Código de confirmação errado recusado; correto desativa o servidor antigo, que passa a recusar login | aprovado |
| Documento danificado no servidor: exportação falha e o servidor volta ao normal | aprovado |
| Cancelar a migração: servidor volta a ser o oficial e o pacote é apagado | aprovado |
| Falha na conferência: banco novo volta a ficar vazio e a importação pode ser repetida | aprovado |
| Somente a Master; servidor em migração não faz backups nem envia avisos | aprovado |
| Aplicativo recusa o servidor antigo depois de conectar ao novo | aprovado |
| Telas: exportar, importar pelo assistente inicial, relatório em PDF e concluir | aprovado |

## Observações para a instalação real

- As pastas são sempre do computador servidor (o HD externo precisa estar ligado nele).
- A linha de comando `AdvogaFacilServidor.exe importar-migracao --pacote "..."` faz a mesma importação, para quando o aplicativo não puder ser aberto no computador novo.
- Depois da migração: endereço do servidor novo nos computadores, Tailscale no computador novo, conta de envio, senha da cópia dos backups e um backup completo.
