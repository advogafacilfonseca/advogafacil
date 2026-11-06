# Configurar o envio dos avisos pelo Google

Este passo a passo é feito **uma única vez**, pela Advogada Master, com a **conta oficial de
envio do escritório** (Gmail ou Google Workspace). Leva poucos minutos.

O Advoga Fácil **nunca vê nem guarda a senha** dessa conta. A autorização é feita na tela do
próprio Google, e o sistema recebe somente a permissão de **enviar** e-mails: ele não lê a
caixa de entrada.

> Os nomes dos menus do Google Cloud mudam de vez em quando. Se algum item não estiver com o
> nome exato abaixo, procure o equivalente na mesma área.

## 1. Criar o projeto no Google Cloud

1. Acesse <https://console.cloud.google.com> entrando com a **conta oficial de envio**.
2. No topo da página, clique no seletor de projetos e em **Novo projeto**. Nome sugerido:
   `Advoga Fácil`. Clique em **Criar** e selecione o projeto criado.

## 2. Ativar a Gmail API

1. Menu ☰ → **APIs e serviços** → **Biblioteca**.
2. Pesquise **Gmail API**, abra e clique em **Ativar**.

## 3. Tela de consentimento (identificação do aplicativo)

1. Menu ☰ → **APIs e serviços** → **Tela de consentimento OAuth** (em algumas versões:
   **Google Auth Platform**).
2. Nome do aplicativo: `Advoga Fácil`. E-mail de suporte e de contato: o e-mail do escritório.
3. Público / tipo de usuário:
   - **Google Workspace** (domínio próprio): escolha **Interno**.
   - **Gmail comum** (@gmail.com): escolha **Externo**.
4. Em **Escopos** (ou **Acesso a dados**), adicione o escopo
   `https://www.googleapis.com/auth/gmail.send` ("Enviar e-mail em seu nome").
5. **Somente para Gmail comum (Externo):** na área **Público**, clique em **Publicar
   aplicativo** (status "Em produção"). Se ficar em "Teste", o Google encerra a autorização
   a cada 7 dias e os e-mails param de sair.

## 4. Criar o identificador do aplicativo (cliente OAuth)

1. Menu ☰ → **APIs e serviços** → **Credenciais** (ou **Clientes**) → **Criar credenciais** →
   **ID do cliente OAuth**.
2. Tipo de aplicativo: **App para computador** (Desktop app). Nome: `Advoga Fácil`.
3. Copie o **ID do cliente** e a **Chave secreta do cliente**.

## 5. Conectar no Advoga Fácil

1. Entre no Advoga Fácil como Master → menu **Notificações** → aba **Conta de envio**.
2. Cole o **ID do cliente** e a **Chave secreta** e clique em **Conectar conta Google**.
3. O navegador abre a página do Google. Entre com a **conta oficial de envio** e autorize.
   - Gmail comum: o Google pode mostrar "O Google não verificou este app". É o aplicativo do
     próprio escritório: clique em **Avançado** → **Acessar Advoga Fácil**.
4. Volte ao Advoga Fácil: a tela mostra "Os avisos são enviados por …".
5. Clique em **Enviar e-mail de teste** e confira a caixa de entrada (e a pasta de spam).
6. Na aba **Quem recebe**, marque quem recebe cada tipo de aviso e salve.

## Segurança e manutenção

- A autorização fica guardada no servidor, criptografada com uma chave que existe só naquele
  computador. Se o servidor for trocado (migração), **conecte a conta de novo**: por segurança
  a autorização não é levada junto.
- Para cancelar o acesso a qualquer momento: <https://myaccount.google.com/permissions> →
  Advoga Fácil → **Remover acesso**. Depois, em Notificações → Conta de envio, clique em
  **Desconectar**.
- Se a autorização for cancelada ou expirar, o histórico de envios mostra "A autorização da
  conta Google foi revogada ou expirou" e os avisos continuam aparecendo no aplicativo. Basta
  conectar de novo.
