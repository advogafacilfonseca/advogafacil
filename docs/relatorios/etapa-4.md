# Relatório — Etapa 4 (Processos e documentos)

Data: 06/11/2026. Ambiente de testes: PostgreSQL 16.15, Python 3.13, PySide6 6.12 (modo offscreen).
Testes também executados no GitHub Actions (Ubuntu) a cada envio.

**Resultado: 85 testes automatizados (projeto inteiro), 85 aprovados.**

## Entregue nesta etapa

- Seção **Processos** (permissão "Processos") com todos os campos definidos: número CNJ, cliente
  vinculado, tipo de ação, área jurídica, tribunal, comarca, vara, parte contrária, advogado
  responsável, data de distribuição, situação, fase processual, próxima audiência ou prazo
  (tipo, data/hora e descrição), descrição e observações.
- **Ficha do processo** com as abas Dados, Movimentações, Documentos e Histórico.
- **Movimentações**: registro com data, descrição, quem registrou e quando. Não podem ser
  alteradas nem apagadas (o banco de dados impede); correções entram como nova movimentação.
- Seção **Documentos** (permissão "Documentos"): anexar vários arquivos de uma vez (PDF,
  imagens, Word e outros formatos), abrir, salvar cópia, renomear, mudar o processo vinculado,
  remover com motivo. A Master vê os removidos e pode restaurá-los.
- **Ficha do cliente** ganhou as abas Processos e Documentos (conforme as permissões).
- **Pesquisa global** passou a encontrar processos (pelo número, com ou sem pontuação, pela
  parte contrária e pelo tipo de ação) e documentos (pelo nome e descrição).

## Como os documentos ficam guardados

- No servidor, em `C:\ProgramData\AdvogaFacil\documentos\<cliente>\<processo ou geral>\`,
  fora de pastas temporárias e separados do programa. Nada é apagado ao atualizar ou reinstalar.
- O banco guarda nome, tamanho, tipo, quem anexou e a impressão SHA-256 de cada arquivo. Ao
  abrir ou salvar uma cópia, o aplicativo confere a impressão antes de usar o arquivo.
- "Abrir" usa uma cópia de leitura neste computador, apagada ao entrar e ao sair do sistema.
- Programas e scripts (.exe, .bat, .ps1, .js, .lnk etc.) são recusados por segurança.
- Limite de 200 MB por arquivo.

## Regras verificadas por testes

| Regra | Resultado |
| --- | --- |
| Número CNJ conferido pelo dígito verificador; número repetido é recusado | aprovado |
| Processo sem número (ex.: inquérito ainda sem numeração) é aceito | aprovado |
| Próxima audiência/prazo exige tipo e data juntos | aprovado |
| Duas pessoas editando o mesmo processo: a segunda é avisada, nada é sobrescrito | aprovado |
| Movimentações não podem ser alteradas nem apagadas; processos não podem ser apagados | aprovado |
| Pesquisa por número completo, sem pontuação ou parcial; por parte contrária sem acento | aprovado |
| Pesquisa global mistura clientes, processos e documentos com paginação correta | aprovado |
| Cada tipo aparece na pesquisa só para quem tem a permissão correspondente | aprovado |
| Quem tem só "Processos" ou "Documentos" escolhe o cliente vendo apenas nome e situação | aprovado |
| Arquivos organizados por cliente/processo; mudar o processo move o arquivo | aprovado |
| Conteúdo baixado é idêntico ao enviado (SHA-256) | aprovado |
| Reenvio do mesmo anexo após queda de conexão não duplica | aprovado |
| Programas e scripts recusados; nome com pastas é limpo | aprovado |
| Remoção exige motivo, preserva o arquivo; só a Master consulta e restaura | aprovado |
| Arquivo ausente no servidor gera aviso claro (restaurar da cópia de segurança) | aprovado |
| Anexar, remover, restaurar, alterar e baixar ficam na auditoria | aprovado |

## O que fica para as próximas etapas

- A data de "próxima audiência ou prazo" passará a gerar compromisso e aviso automático na
  Agenda e na Central de Pendências (etapa 6) e e-mail (etapa 7).
- Cópias de segurança automáticas dos documentos entram na etapa 9 (Central de Backup).
