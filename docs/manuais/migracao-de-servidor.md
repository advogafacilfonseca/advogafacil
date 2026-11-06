# Guia de migração do servidor

Use este guia para trocar o computador servidor do Advoga Fácil (por exemplo, um notebook novo). A migração leva **tudo**: usuários, senhas e permissões, clientes, processos, documentos, contratos, parcelas, pagamentos e comprovantes, agenda e pendências, configurações e todo o histórico. Ninguém precisa recadastrar nada.

> Se o servidor antigo **quebrou ou foi roubado**, não é migração: siga o **Guia de recuperação de dados** (restauração do backup).

## Como a migração protege os dados

- **Nada fica para trás.** Ao exportar, o servidor antigo entra em **modo somente leitura**: a equipe continua consultando, mas ninguém grava alterações. As gravações que estavam em andamento terminam antes da exportação.
- **Tudo é conferido.** O servidor novo confere cada tabela (número de registros e uma impressão digital do conteúdo) e cada documento (SHA-256). Se algo não conferir, a importação é desfeita e o servidor novo continua vazio, pronto para tentar de novo.
- **Nunca há duas bases oficiais.** No fim, o servidor antigo é **desativado** com o código de confirmação gerado pelo servidor novo. Depois disso, ele não aceita mais login. Os computadores do escritório que já conectaram ao servidor novo também passam a recusar o servidor antigo, mesmo que alguém o ligue de novo.
- **Segredos não viajam.** O pacote é criptografado com uma senha que você escolhe e que não fica gravada. A autorização do Google (conta de envio de e-mail) e a senha da cópia criptografada dos backups **não** são transferidas: você as configura de novo no servidor novo.

## Antes de começar

1. Escolha um horário sem expediente: durante a migração ninguém consegue gravar nada.
2. Tenha um **HD externo ou pen drive** com espaço para o banco e todos os documentos.
3. No computador novo, instale o **Advoga Fácil Servidor** (o mesmo instalador do servidor). Ele cria um banco vazio e o arquivo `CODIGO_DE_INSTALACAO.txt` na pasta `C:\ProgramData\AdvogaFacil\config`. **Não crie a conta Master no computador novo.**
4. Faça um **backup completo** na Central de Backups do servidor antigo, por segurança.

## Passo 1: exportar no servidor antigo

1. Entre no Advoga Fácil como Master e abra **Migração de servidor**.
2. Em **Pasta do pacote**, informe uma pasta do HD externo ligado ao **computador servidor antigo** (ex.: `E:\Migracao`) e clique em **Verificar**.
3. Defina a **senha do pacote** (mínimo de 12 caracteres) e anote-a. Confirme a sua senha de login.
4. Clique em **Exportar para o servidor novo** e confirme. O aviso de andamento mostra cada etapa.
5. No fim, aparece o caminho do pacote, por exemplo `E:\Migracao\AdvogaFacil_Migracao_2026-11-06_200000.afmig`. O servidor antigo fica em **somente leitura**.

Se a exportação falhar (por exemplo, um documento danificado no servidor), nada muda: o servidor volta ao normal e a mensagem explica o problema.

## Passo 2: importar no servidor novo

1. Desligue o HD do servidor antigo e ligue-o no **computador novo**.
2. No computador novo, abra o aplicativo Advoga Fácil e conecte ao servidor dele (`127.0.0.1` ou o nome do computador).
3. Na tela "Criar a conta da Advogada Master", clique em **Importar dados de outro servidor**.
4. Informe:
   - o **código de instalação** (arquivo `C:\ProgramData\AdvogaFacil\config\CODIGO_DE_INSTALACAO.txt` do computador novo);
   - o **caminho do pacote** no computador novo (ex.: `E:\Migracao\AdvogaFacil_Migracao_2026-11-06_200000.afmig`);
   - a **senha do pacote**.
5. Clique em **Importar** e aguarde. No fim aparece o relatório, tabela por tabela, e o **código de confirmação** (formato `XXXX-XXXX-XXXX`). **Anote o código.** O relatório também fica gravado em `C:\ProgramData\AdvogaFacil\migracoes`.
6. Clique em **Ir para o login** e entre com o seu usuário e senha de sempre.

**Alternativa pela linha de comando** (Prompt de Comando como administrador, no computador novo):

```
"C:\Program Files\Advoga Fácil Servidor\servidor\AdvogaFacilServidor.exe" importar-migracao --pacote "E:\Migracao\AdvogaFacil_Migracao_2026-11-06_200000.afmig"
```

## Passo 3: concluir no servidor antigo

1. No servidor antigo, abra **Migração de servidor** (o login ainda funciona, só a gravação está bloqueada).
2. Em **Concluir a migração**, informe o **código de confirmação** e a sua senha.
3. Clique em **Concluir e desativar este servidor**. O servidor antigo é desativado de forma definitiva.

Você pode baixar o relatório em PDF de cada etapa em **Migração de servidor > Histórico > Salvar relatório em PDF**.

## Passo 4: depois da migração

No servidor novo, a Master recebe um aviso com o que falta. Normalmente:

1. **Nos computadores do escritório**, se o endereço do servidor mudou, abra o aplicativo, clique em **Alterar servidor** na tela de login e informe o endereço novo. Na primeira conexão, confira a impressão digital do certificado do servidor novo.
2. **Tailscale:** instale e entre na Tailscale no computador novo, com a mesma conta do escritório, e use o nome dele na Tailscale como endereço nos computadores remotos.
3. **Notificações > Conta de envio:** conecte de novo a conta Google (guia "Configurar o envio pelo Google").
4. **Central de Backups:** confira a pasta do HD de backup no computador novo, defina de novo a senha da cópia criptografada, faça um **backup completo** e um **teste de restauração**.

## Cancelar uma migração

Se você exportou mas **ainda não importou** o pacote em outro computador, pode cancelar: em **Migração de servidor**, confirme a sua senha e clique em **Cancelar a migração**. O servidor antigo volta a ser o oficial e o pacote gerado é apagado.

> **Não cancele depois de importar.** Se o pacote já foi importado, conclua a migração com o código de confirmação. Se mesmo assim o servidor antigo voltar a funcionar, os computadores que já conectaram ao servidor novo recusam o antigo automaticamente.
