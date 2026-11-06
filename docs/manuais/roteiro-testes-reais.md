# Roteiro dos testes reais

Faça este roteiro antes de cadastrar os dados reais do escritório. Use **dados inventados** (cliente "Teste da Silva", processo de teste), nunca dados de clientes reais. Ao terminar, anote o resultado de cada item (OK ou o problema encontrado) e envie a lista.

Você vai precisar de: o notebook que será o servidor, um segundo computador (de preferência um notebook), um HD externo ou pen drive, e o celular para usar a internet dele no item 6.

## 1. Instalação

- [ ] 1.1 Instalar o **Advoga Fácil Servidor** no notebook da Master (manual de instalação, seção 3). A instalação termina sem erro.
- [ ] 1.2 No menu Iniciar > Advoga Fácil Servidor, os atalhos **Código de instalação** e **Como conectar os computadores** abrem.
- [ ] 1.3 Instalar o **aplicativo** no próprio servidor, conectar em `127.0.0.1` e conferir a impressão digital com o arquivo **Como conectar**.
- [ ] 1.4 Criar a conta Master com o código de instalação.

## 2. Equipe e permissões

- [ ] 2.1 Criar dois usuários de teste: "assistente" (clientes, processos, agenda, documentos) e "financeiro" (clientes, contratos, financeiro).
- [ ] 2.2 Entrar como "assistente" no segundo computador: o sistema pede a troca da senha provisória.
- [ ] 2.3 O "assistente" **não** vê Contratos, Financeiro, Usuários, Backups nem Auditoria.
- [ ] 2.4 O "assistente" tenta entrar 5 vezes com a senha errada: fica bloqueado por 15 minutos.

## 3. Rede do escritório

- [ ] 3.1 Instalar o aplicativo no segundo computador, ligado no mesmo Wi-Fi, e conectar pelo nome do servidor (arquivo **Como conectar**).
- [ ] 3.2 Cadastrar um cliente de teste no segundo computador e vê-lo aparecer no servidor.
- [ ] 3.3 Duas pessoas editam o mesmo cliente ao mesmo tempo: quem salva por último recebe o aviso para recarregar.

## 4. Uso diário

- [ ] 4.1 Cadastrar um processo de teste e uma movimentação.
- [ ] 4.2 Anexar um PDF e uma foto ao cliente, abrir os dois e salvar uma cópia.
- [ ] 4.3 Criar uma audiência para amanhã e uma pendência para hoje. Elas aparecem no Painel e na Agenda.
- [ ] 4.4 Criar um contrato com entrada e 3 parcelas e registrar um recebimento com comprovante.
- [ ] 4.5 Gerar um relatório e exportar em PDF e em Excel.
- [ ] 4.6 Pesquisar "teste" (sem acento e em minúsculas) no alto da tela.

## 5. E-mail

- [ ] 5.1 Conectar a conta Google oficial (guia `configurar-envio-google.md`) e enviar o e-mail de teste.
- [ ] 5.2 Escolher você como destinatária das audiências e clicar em **Verificar avisos agora**: o aviso da audiência de amanhã chega no aplicativo e no e-mail.
- [ ] 5.3 O e-mail de aviso financeiro **não** mostra valores.

## 6. Acesso de fora do escritório (Tailscale)

- [ ] 6.1 Instalar a Tailscale no servidor e no segundo computador, com a mesma conta (manual de instalação, seção 6).
- [ ] 6.2 Rodar o comando `informacoes` no servidor: o arquivo **Como conectar** passa a mostrar o nome da Tailscale.
- [ ] 6.3 Ligar o segundo computador na **internet do celular** (fora da rede do escritório) e conectar pelo nome da Tailscale. O sistema funciona normalmente.
- [ ] 6.4 Desligar a Tailscale no segundo computador: o aplicativo avisa que o servidor está indisponível (o servidor não fica exposto na internet).

## 7. Queda de conexão e reinício

- [ ] 7.1 Com um cadastro aberto, desligar o Wi-Fi do segundo computador e tentar salvar: aparece o aviso de conexão, e nada é gravado em duplicidade depois que a rede volta.
- [ ] 7.2 Reiniciar o notebook servidor: depois de ligar, o sistema volta sozinho, sem ninguém precisar entrar no Windows.

## 8. Backups

- [ ] 8.1 Configurar a Central de Backups com o HD externo, definir a senha da cópia criptografada, fazer um **backup completo** e um **teste de restauração**. Os dois ficam "Concluído".
- [ ] 8.2 Desligar o HD e clicar em **Fazer backup completo agora**: aparece o alerta de HD desconectado.

## 9. Migração (opcional, se houver um terceiro computador)

- [ ] 9.1 Seguir o **Guia de migração do servidor** para um computador de teste. O relatório mostra "Idêntico" em todas as linhas.
- [ ] 9.2 Concluir no servidor antigo com o código de confirmação. Ele passa a recusar o login.
- [ ] 9.3 Como os dados são de teste, depois desinstale o servidor do computador de teste.

## 10. Depois dos testes

Quando tudo estiver OK, os dados de teste podem ficar (eles não atrapalham) ou o servidor pode ser reinstalado do zero antes de começar com os dados reais. Nesse caso, desinstale o servidor, apague a pasta `C:\ProgramData\AdvogaFacil` e instale de novo.
