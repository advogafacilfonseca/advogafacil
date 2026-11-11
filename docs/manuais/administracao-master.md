# Manual de administração da Advogada Master

A conta Master tem autoridade total e é única. Ela não pode ser desativada nem perder a autoridade por alteração direta no banco de dados. Este manual reúne as tarefas que só a Master faz.

## 1. Primeiros passos depois da instalação

Faça nesta ordem:

1. **Usuários e Permissões:** cadastre a equipe (seção 2).
2. **Notificações > Conta de envio:** conecte a conta Google oficial do escritório (guia `configurar-envio-google.md`).
3. **Notificações:** escolha quem recebe cada tipo de aviso (seção 3).
4. **Central de Backups:** configure o HD externo, a cópia criptografada, faça um backup completo e um teste de restauração (guia `recuperacao-de-dados.md`).
5. Instale a **Tailscale** no servidor e nos notebooks que trabalham fora (manual de instalação, seção 6).

## 2. Usuários e permissões

Menu **Usuários e Permissões**.

- **Novo usuário:** nome, usuário, e-mail, cargo e uma **senha provisória** (o botão **Gerar outra** sugere uma senha forte). No primeiro acesso, a pessoa é obrigada a criar a própria senha. Entregue a senha provisória pessoalmente, nunca por e-mail.
- **Permissões:** marque o que cada pessoa pode acessar e clique em **Salvar permissões**. As permissões são conferidas no servidor em toda operação: um menu escondido não basta, o servidor recusa o acesso e registra a tentativa.

| Permissão | Libera |
| --- | --- |
| Acesso aos clientes | Cadastro e ficha dos clientes |
| Acesso aos processos | Processos e movimentações |
| Acesso aos contratos | Contratos **sem valores** |
| Acesso ao financeiro | Valores, parcelas, recebimentos, despesas e relatórios financeiros. Para criar contratos, são necessárias as duas: contratos e financeiro |
| Acesso à agenda | Agenda e compromissos |
| Acesso às pendências | Central de Pendências |
| Acesso aos documentos | Anexar, abrir e remover documentos |
| Recebimento de notificações | Pode ser escolhida como destinatária de avisos |
| Administração de usuários | Cadastrar usuários e ajustar permissões de outras pessoas |
| Configurações do sistema | Configurações gerais |

**Regras de segurança (garantidas pelo servidor):**

- Ninguém altera as próprias permissões, nem quem tem "Administração de usuários".
- Ninguém, além da Master, concede ou retira a autoridade Master.
- Usuários não são apagados: use **Desativar usuário**. O histórico continua com o nome de quem fez cada coisa. A desativação encerra na hora as sessões abertas da pessoa.
- **Redefinir senha** gera uma senha provisória nova, e a pessoa troca no próximo acesso.

**Saída de um funcionário:** desative o usuário no mesmo dia, retire o computador dele da Tailscale (painel `login.tailscale.com`) e confira na **Auditoria** as últimas atividades.

**Esqueceu a senha da Master?** No próprio notebook servidor, abra o menu Iniciar > **Advoga Fácil Servidor > Recuperar a senha da Master**, aceite o pedido de administrador do Windows e digite **SIM**. A tela mostra uma **senha provisória**: entre com ela no Advoga Fácil e crie uma senha nova. A senha antiga deixa de funcionar, as sessões abertas da Master são encerradas e a recuperação fica registrada na Auditoria e nos avisos. Só funciona no computador servidor, por quem é administrador do Windows; não existe recuperação pela internet nem por e-mail.

## 3. Notificações

Menu **Notificações** (só a Master).

- **Conta de envio:** a conta Google oficial do escritório envia todos os e-mails automáticos. O sistema guarda só uma autorização limitada ao envio, criptografada, e nunca a senha do Gmail. Use **Enviar e-mail de teste** para conferir.
- **Destinatários:** para cada categoria (audiências, reuniões, prazos, ligações e retornos, outros compromissos, atrasados e financeiro), escolha quem recebe no aplicativo e quem recebe por e-mail. Os avisos do financeiro só podem ir para quem tem acesso ao financeiro, e os e-mails **nunca** mostram valores.
- **Histórico de envios:** mostra cada e-mail, a situação e o erro, se houve. **Reenviar e-mail** tenta de novo.
- Os avisos são gerados pelo próprio servidor, mesmo com todos os aplicativos fechados. **Verificar avisos agora** força uma verificação.

## 4. Central de Backups

Siga o **Guia de recuperação de dados** (`recuperacao-de-dados.md`). Rotina mínima:

- **Toda semana:** abrir a Central de Backups e conferir se não há alertas e se o último teste de restauração foi "Concluído".
- **Todo mês:** trocar o HD externo por um segundo HD guardado fora do escritório, se usar dois.
- **A cada 6 meses:** restaurar num computador de teste, para treinar o procedimento.

A senha da cópia criptografada não fica gravada em lugar nenhum: guarde-a em papel, em local seguro.

## 5. Auditoria

Menu **Auditoria** (só a Master). Mostra quem fez o quê e quando: entradas e saídas, tentativas de login erradas, acessos negados, alterações de cadastro com o valor anterior, exportações de relatórios, backups e migrações. Filtre por pessoa, ação e período. Os registros de auditoria não podem ser alterados nem apagados, nem diretamente no banco de dados.

## 6. Trocar o computador servidor

Siga o **Guia de migração do servidor** (`migracao-de-servidor.md`). Em resumo: exportar no servidor antigo, importar no novo, concluir no antigo com o código de confirmação. Ninguém precisa recadastrar nada e o sistema impede que os dois servidores funcionem como oficiais ao mesmo tempo.

Se o servidor **quebrou ou foi roubado**, não há migração: restaure o último backup no computador novo (guia de recuperação).

## 7. Atualizações

Siga o **Manual de instalação, seção 7**. O instalador do servidor faz uma cópia do banco antes de atualizar. Prefira atualizar fora do expediente.

## 8. Lista de verificação mensal

- [ ] Central de Backups sem alertas, último teste de restauração "Concluído".
- [ ] Histórico de envios sem falhas repetidas (se houver, confira a conta Google em **Conta de envio**).
- [ ] Usuários ativos conferidos: só quem ainda trabalha no escritório.
- [ ] Computadores na Tailscale conferidos: só os do escritório.
- [ ] Auditoria: nenhuma sequência estranha de "acesso negado" ou de logins errados.
- [ ] Espaço livre no notebook servidor e no HD de backup.
- [ ] Windows Update em dia no servidor (reinicie fora do expediente).
