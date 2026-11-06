# Relatório da etapa 11: instaladores, Tailscale e manuais

Data: 06/11/2026.

**Resultado: 158 testes automatizados passaram. Além deles, a cada envio ao GitHub, os dois instaladores são instalados de verdade num computador Windows (Windows Server 2025, mesma base do Windows 11).** O teste do servidor instala, confere, atualiza por cima e desinstala.

## O que foi entregue

| Item | Como ficou |
| --- | --- |
| Instalador do servidor | Instala a API, o PostgreSQL 16 (só em 127.0.0.1, senhas aleatórias), os dois serviços do Windows (iniciam sozinhos) e as regras de firewall. Gera o código de instalação e o arquivo **Como conectar os computadores**. |
| Atualização segura | O instalador para os serviços, faz uma **cópia do banco** antes de mexer na estrutura (as 5 últimas ficam guardadas) e só então atualiza. Se a cópia falhar, o banco não é alterado. |
| Falha na instalação | Se a configuração do servidor falhar, o instalador avisa na tela e indica o registro (antes, ele terminava como se estivesse tudo certo). |
| Instalador do aplicativo | Instala o Advoga Fácil em cada computador, com atalho opcional na área de trabalho. |
| Firewall | Rede local só em redes marcadas como Particular ou de Domínio. Tailscale (100.64.0.0/10) em qualquer rede. Nenhuma porta do PostgreSQL é aberta. |
| Tailscale | Passo a passo no manual de instalação (conta do escritório, execução sem login, chave sem expiração, remoção de computadores perdidos). O comando `informacoes` detecta a Tailscale e mostra o endereço do servidor nela. |
| Manuais | Instalação, uso, administração da Master e roteiro dos testes reais, além dos guias de e-mail, recuperação e migração. |

## Problemas encontrados pelo teste real do instalador (e corrigidos)

O teste real no Windows achou dois defeitos que os testes comuns não pegariam. Os dois teriam impedido a instalação no notebook:

1. **O banco não era criado.** O `initdb` do PostgreSQL abandona os privilégios de administrador ao rodar e não tinha acesso à pasta protegida `C:\ProgramData\AdvogaFacil`. Agora o instalador dá acesso temporário só à pasta do banco e o retira logo depois.
2. **Acento no nome da pasta do programa.** O PostgreSQL não inicializa numa pasta com acento ("Advoga Fácil Servidor"). A pasta do programa passou a ser `C:\Program Files\AdvogaFacilServidor`. O nome exibido no Windows continua "Advoga Fácil Servidor".

Também corrigido: os scripts e instaladores agora são gravados em UTF-8 com marcação (BOM), para os acentos aparecerem certos no Windows.

## Conferido no Windows, a cada envio

| Verificação | Resultado |
| --- | --- |
| Instalação nova: serviços no ar, banco ok, sistema aguardando a conta Master | aprovado |
| Código de instalação e arquivo "Como conectar" gerados | aprovado |
| PostgreSQL escutando só em 127.0.0.1 | aprovado |
| Regras de firewall: rede do escritório (Particular/Domínio) e Tailscale | aprovado |
| Atualização por cima: mesma identidade do servidor, cópia do banco feita antes | aprovado |
| Desinstalação: serviços e regras removidos, dados preservados | aprovado |
| Instalador do aplicativo | aprovado |

## O que ainda depende do escritório

A **rodada de testes reais** com o notebook da Master e outro computador, seguindo `docs/manuais/roteiro-testes-reais.md`: rede do escritório, Tailscale fora do escritório, conta Google, HD de backup e reinício do notebook.

O instalador não tem **assinatura digital** (certificado de assinatura de código, que é comprado). Por isso, o Windows mostra o aviso "O Windows protegeu o computador" na primeira execução. O manual de instalação explica como prosseguir.
