# Guia de recuperação de dados

Este guia explica como recuperar o Advoga Fácil depois de uma falha, roubo, corrupção ou defeito do computador servidor. Ele foi escrito para a Advogada Master.

> **Regra de ouro:** sincronização de pastas (OneDrive, Google Drive, Dropbox) **não** é backup. Se um arquivo for apagado ou danificado, a sincronização copia o estrago. Use a **Central de Backups**.

## 1. Como os backups funcionam

O Advoga Fácil faz três tipos de cópia:

| Cópia | Quando | Onde | O que contém |
| --- | --- | --- | --- |
| **Backup completo** | Todo dia, no horário escolhido (padrão 23:00) | HD externo | Banco inteiro e todos os documentos e comprovantes, **conferidos um a um** |
| **Backup rápido** | A cada poucas horas (padrão 4 h) | HD externo | Banco inteiro e somente os documentos novos |
| **Cópia criptografada** | A cada backup completo (se ligada) | Outro local: segundo HD, pasta de rede ou pasta sincronizada | O mesmo conteúdo do completo, num único arquivo `.afbk` protegido por senha |

**Cada versão é um ponto completo de restauração.** Os documentos ficam guardados uma única vez no HD, porque o conteúdo de um documento nunca muda. Por isso os backups rápidos são leves.

**Conferências automáticas:**

- Toda cópia é conferida pela impressão digital (SHA-256), e o banco é lido de volta logo depois de gravado.
- O backup completo confere de novo cada documento, no HD e no próprio servidor. Assim ele também percebe arquivos corrompidos no disco do servidor e mantém a cópia boa no backup.
- A cada 7 dias (ajustável), o sistema **restaura o último backup num banco de teste** e confere se todos os registros voltaram. Depois apaga o banco de teste.

**Alertas para a Master** (no botão "Avisos" e por e-mail, se a conta de envio estiver conectada):

- falha em qualquer backup ou teste;
- HD externo desconectado (um aviso por dia);
- falta de espaço.

A Central de Backups também mostra um aviso quando o último backup completo tem mais de 26 horas.

## 2. Configuração recomendada

1. Ligue um **HD externo dedicado** ao computador servidor (por exemplo, `E:`). De preferência, proteja-o com o **BitLocker To Go**: clique com o botão direito no HD > *Ativar o BitLocker*.
2. No Advoga Fácil, abra **Central de Backups > Configuração**.
   - Pasta no HD externo: `E:\Backups` e depois **Verificar**.
   - Deixe marcado "Fazer backups automáticos" e clique em **Salvar configuração**.
3. **Cópia criptografada (recomendada):** escolha um **segundo local**, que não seja o mesmo HD. Pode ser um segundo HD guardado fora do escritório ou uma pasta sincronizada com a nuvem.
   - Defina a senha da cópia (no mínimo 12 caracteres) e **anote-a em papel, guardado em local seguro**. A senha não fica gravada no sistema. Sem ela, a cópia não pode ser aberta.
4. Clique em **Fazer backup completo agora** e depois em **Testar restauração agora**. Confira no histórico que os dois ficaram "Concluído".

> As pastas são do **computador servidor**. Um HD ligado em outro computador não é visto pelo servidor. Pastas de rede devem ser informadas pelo caminho completo (`\\servidor\pasta`). O serviço do Advoga Fácil precisa ter permissão de gravação nelas.

**Retenção:** as versões ficam guardadas pelo número de dias escolhido (padrão 60). As três últimas versões completas nunca são apagadas.

## 3. Situações e o que fazer

### HD externo desconectado ou cheio

Reconecte o HD com a mesma letra de unidade ou troque por um maior. Depois clique em **Fazer backup completo agora**. Se a letra mudou, corrija a pasta na configuração.

### Documento danificado no servidor

O backup completo avisa "Arquivo alterado ou corrompido no servidor (a cópia boa está no backup)". Não apague nada e fale com o suporte técnico: a cópia boa está em `E:\Backups\AdvogaFacil-Backups\documentos\...`, no mesmo caminho do original.

### Computador servidor com defeito, roubado ou com o banco corrompido

Restaure o sistema num computador novo (ou no mesmo, depois de formatado):

1. Instale o **Advoga Fácil Servidor** no computador novo. Ele cria um banco vazio. **Não crie a conta Master de novo.**
2. Abra o **Prompt de Comando como administrador** e pare o serviço:
   ```
   net stop AdvogaFacilServidor
   ```
3. Ligue o HD externo e rode a restauração. O caminho do programa pode variar:
   ```
   "C:\Program Files\AdvogaFacilServidor\servidor\AdvogaFacilServidor.exe" restaurar --origem "E:\Backups"
   ```
   O sistema usa a **versão mais recente**. Para escolher outra versão, informe a pasta dela, por exemplo `--origem "E:\Backups\AdvogaFacil-Backups\versoes\2026-11-06_230000_completo"`.

   **Se o HD também se perdeu,** use a cópia criptografada. O sistema pedirá a senha da cópia:
   ```
   ...AdvogaFacilServidor.exe restaurar --origem "F:\CopiaAdvogaFacil\AdvogaFacil_2026-11-06_230000.afbk"
   ```
4. A restauração **confere tudo antes**: banco e cada documento pelo manifesto. Se algo estiver danificado, ela para sem mexer em nada. Ela só grava num banco novo ou recém-instalado, e **nunca apaga um banco que já tenha dados**. No fim, ela confere de novo as contagens e os documentos.
5. Inicie o serviço:
   ```
   net start AdvogaFacilServidor
   ```
6. Nos computadores do escritório, abra o Advoga Fácil. Se o endereço do servidor mudou, informe o novo endereço. Todos entram com os mesmos usuários e senhas.
7. Em **Notificações > Conta de envio**, conecte a conta Google de novo. Em **Central de Backups**, confira a configuração e defina de novo a senha da cópia criptografada. Por segurança, essas autorizações não são transferidas de um computador para outro.
8. Faça um **backup completo** e um **teste de restauração** no servidor novo.

> **Importante:** depois de restaurar em outro computador, **não volte a usar o servidor antigo** como base oficial. Se ele for recuperado, desligue o serviço do Advoga Fácil nele. Para trocar de computador com os dois funcionando, use o **Guia de migração do servidor** (`migracao-de-servidor.md`): ele desativa o servidor antigo automaticamente.

### Restaurar um arquivo ou dado apagado por engano

O sistema não apaga registros: clientes, processos, contratos, pagamentos e documentos ficam no histórico. Se mesmo assim for preciso consultar uma versão antiga, faça a restauração (passos acima) num **computador de teste**, nunca no servidor oficial, e consulte os dados lá.

## 4. Rotina sugerida

- **Toda semana:** abra a Central de Backups e confira se não há alertas e se o último teste de restauração foi "Concluído".
- **Todo mês:** se usar dois HDs, troque o HD externo por um segundo HD guardado fora do escritório.
- **A cada 6 meses:** faça uma restauração completa num computador de teste, seguindo a seção 3, para treinar o procedimento.
