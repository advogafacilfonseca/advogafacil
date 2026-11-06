# Manual de instalação

Este manual explica como instalar o Advoga Fácil no escritório: o **servidor** no notebook da Advogada Master e o **aplicativo** em cada computador que vai usar o sistema.

## 1. Visão geral

| Peça | Onde instalar | O que faz |
| --- | --- | --- |
| **Advoga Fácil Servidor** | Somente no computador servidor (notebook da Master) | Guarda o banco de dados (PostgreSQL) e os documentos, e atende os computadores |
| **Advoga Fácil** (aplicativo) | Em todos os computadores, inclusive no servidor | Tela do sistema. Não guarda dados do escritório |
| **Tailscale** | No servidor e nos computadores que acessam de fora do escritório | Rede privada e criptografada entre os computadores do escritório |

Onde ficam os dados no servidor: `C:\ProgramData\AdvogaFacil` (banco, documentos, configuração e registros). O programa fica em `C:\Program Files\Advoga Fácil Servidor`. Desinstalar o programa **não** apaga os dados.

**Requisitos:** Windows 10 ou 11 de 64 bits, conta de administrador para instalar, e pelo menos 10 GB livres no servidor (mais o tamanho dos documentos). Recomendado: um HD externo para os backups.

## 2. Onde baixar os instaladores

Os instaladores são gerados automaticamente no GitHub do projeto a cada atualização, depois que todos os testes passam:

1. Entre em `github.com/advogafacilfonseca/advogafacil` com a conta do escritório.
2. Clique em **Actions**, abra a execução mais recente com o sinal verde e, no fim da página, baixe **instaladores-windows**.
3. Descompacte o arquivo. Dentro dele estão:
   - `AdvogaFacilServidor-Instalador-<versão>.exe` (servidor);
   - `AdvogaFacil-Instalador-<versão>.exe` (aplicativo).

> O Windows pode mostrar "O Windows protegeu o computador" porque o instalador ainda não tem assinatura digital comprada. Clique em **Mais informações > Executar assim mesmo**. Só faça isso com instaladores baixados do GitHub do escritório.

## 3. Instalar o servidor (notebook da Master)

1. Execute `AdvogaFacilServidor-Instalador-<versão>.exe` e aceite o pedido de administrador.
2. Siga o assistente (Avançar, Instalar). Ao terminar, o instalador já:
   - criou o banco PostgreSQL, com senhas aleatórias e acesso **somente pelo próprio computador**;
   - criou e iniciou os serviços do Windows **AdvogaFacilPostgreSQL** e **AdvogaFacilServidor** (iniciam sozinhos quando o Windows liga);
   - liberou no firewall a porta 8765 **somente** para a rede do escritório (redes marcadas como Particular) e para a Tailscale;
   - gerou o **código de instalação** da conta Master e o arquivo **Como conectar os computadores**.
3. No menu Iniciar, na pasta **Advoga Fácil Servidor**, estão os atalhos:
   - **Código de instalação (conta Master)**, usado uma única vez;
   - **Como conectar os computadores**: endereços do servidor e a impressão digital do certificado;
   - **Pasta de dados do servidor**.

**Rede do escritório como "Particular":** em *Configurações > Rede e Internet > Wi-Fi (ou Ethernet) > propriedades da rede*, marque **Rede particular**. Em redes públicas (café, aeroporto), os computadores só alcançam o servidor pela Tailscale.

**Energia:** como o servidor é um notebook, em *Configurações > Sistema > Energia*, ajuste para **não suspender** quando ligado na tomada. Com o notebook suspenso, ninguém acessa o sistema.

## 4. Instalar o aplicativo

Em cada computador (inclusive no próprio servidor):

1. Execute `AdvogaFacil-Instalador-<versão>.exe` e marque, se quiser, o atalho na área de trabalho.
2. Abra o **Advoga Fácil**. Na tela **Conexão com o servidor**, informe o endereço:
   - no próprio servidor: `127.0.0.1`;
   - na rede do escritório: o nome do computador servidor (veja o arquivo **Como conectar os computadores**);
   - fora do escritório: o nome da Tailscale do servidor (seção 6).
3. Clique em **Testar conexão**. O aplicativo mostra a **impressão digital do certificado** do servidor. Confira se ela é igual à do arquivo **Como conectar os computadores** (pelo menos o começo e o fim). Se for, clique em **Salvar e continuar**.

> A impressão digital garante que o computador está falando com o servidor do escritório, e não com um impostor. Ela fica gravada; se um dia o aplicativo avisar que o certificado mudou sem você ter trocado o servidor, **não continue** e fale com o suporte.

## 5. Primeira configuração (uma única vez)

No primeiro acesso ao servidor novo, o aplicativo abre **Criar a conta da Advogada Master**:

1. Abra o atalho **Código de instalação (conta Master)** no servidor e copie o código.
2. Preencha nome, nome de usuário, e-mail e senha (mínimo de 10 caracteres, com letras e números).
3. Clique em **Criar conta Master**. O código deixa de existir.

> Trocando de servidor? **Não** crie a Master: clique em **Importar dados de outro servidor** e siga o Guia de migração do servidor.

Depois, siga o **Manual de administração da Master** para cadastrar a equipe, configurar o e-mail e os backups.

## 6. Tailscale (acesso de fora do escritório)

A Tailscale cria uma rede privada e criptografada só entre os computadores do escritório. O servidor **não** fica exposto na internet e nenhuma porta é aberta no roteador.

1. Crie uma conta gratuita em `tailscale.com` com o e-mail do escritório (a mesma conta será usada em todos os computadores).
2. **No servidor:** baixe e instale a Tailscale para Windows e entre com essa conta. No ícone da Tailscale (perto do relógio), deixe marcado **Run unattended** (*Executar sem estar conectado*), para a Tailscale funcionar mesmo antes de alguém entrar no Windows.
3. No painel `login.tailscale.com/admin/machines`, abra o servidor, clique em **...** e escolha **Disable key expiry**. Assim o servidor não sai da rede a cada 180 dias.
4. Atualize o arquivo de conexão: no servidor, abra o **Prompt de Comando como administrador** e rode:
   ```
   "C:\Program Files\Advoga Fácil Servidor\servidor\AdvogaFacilServidor.exe" informacoes
   ```
   O atalho **Como conectar os computadores** passa a mostrar o nome do servidor na Tailscale (ex.: `notebook-master.tail1234.ts.net`).
5. **Em cada computador que acessa de fora:** instale a Tailscale e entre com a mesma conta. No Advoga Fácil, use o endereço da Tailscale do servidor. Ele funciona dentro e fora do escritório.
6. Por segurança, só adicione à conta da Tailscale computadores do escritório. Para remover um computador perdido ou vendido, apague-o no painel da Tailscale.

## 7. Atualizar para uma versão nova

1. Baixe os instaladores novos (seção 2).
2. **Servidor:** avise a equipe e execute o instalador novo do servidor por cima do atual. Ele:
   - para os serviços;
   - faz uma **cópia de segurança do banco** em `C:\ProgramData\AdvogaFacil\atualizacoes` (as 5 últimas ficam guardadas);
   - atualiza o programa e a estrutura do banco, sem apagar nada, e inicia os serviços de novo.
   Se a cópia de segurança falhar, a atualização para sem alterar o banco.
3. **Aplicativo:** execute o instalador novo em cada computador.

## 8. Desinstalar

Pelo *Painel de Controle > Programas*. A desinstalação do servidor remove os serviços e as regras de firewall, mas **mantém** `C:\ProgramData\AdvogaFacil` (banco e documentos). Apague essa pasta somente se tiver certeza e um backup conferido.

## 9. Problemas comuns

| Sintoma | O que fazer |
| --- | --- |
| "Não foi possível conectar ao servidor" | Confira se o notebook servidor está ligado e acordado. Fora do escritório, confira se a Tailscale está conectada nos dois computadores. |
| Funciona no servidor, mas não em outro computador da rede | Marque a rede do servidor como **Particular** (seção 3) ou use o endereço da Tailscale. |
| Aviso de certificado diferente | Não continue. Só é normal depois de reinstalar ou migrar o servidor. Nesse caso, confira a impressão digital nova no arquivo **Como conectar os computadores** e clique em **Alterar servidor**. |
| "Este servidor foi substituído por um servidor novo" | O escritório migrou de servidor. Informe o endereço do servidor novo. |
| Serviço parado | No servidor, abra *Serviços* do Windows e inicie **Advoga Fácil Servidor**. Os registros ficam em `C:\ProgramData\AdvogaFacil\logs`. |
