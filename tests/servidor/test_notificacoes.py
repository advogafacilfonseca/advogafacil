"""Notificações: destinatários escolhidos pela Master, geração sem duplicidade, envio por e-mail
com registro do resultado, interrupção quando o aviso deixa de valer e sigilo financeiro."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from advoga_server.services import notificacoes as svc
from advoga_server.services.email import ErroEnvio
from tests.conftest import auth, criar_usuario, login
from tests.servidor.test_agenda import novo, quando
from tests.servidor.test_financeiro import contrato, pagar

AGORA = datetime.now(UTC).astimezone()
HOJE = AGORA.date()
DIA = datetime.combine(HOJE, time(12, 0)).astimezone()  # meio-dia: depois do horário de início dos avisos


class EnviadorFalso:
    remetente = "notificacoes@exemplo.com"

    def __init__(self, falhar: ErroEnvio | None = None) -> None:
        self.enviados = []
        self.falhar = falhar

    def enviar(self, msg) -> None:
        if self.falhar:
            raise self.falhar
        self.enviados.append(msg)


@pytest.fixture
def equipe(cliente, token_master, master):
    ana = criar_usuario(cliente, token_master, "ana", permissoes=["agenda", "notificacoes"])
    bia = criar_usuario(cliente, token_master, "bia", permissoes=["pendencias", "financeiro", "notificacoes"])
    caio = criar_usuario(cliente, token_master, "caio", permissoes=["agenda"])  # sem "Recebimento de notificações"
    return {"master": master, "ana": ana, "bia": bia, "caio": caio}


def configurar(cliente, token, **por_categoria):
    atual = cliente.get("/api/notificacoes/configuracao", headers=auth(token)).json()
    cats = []
    for c in atual["categorias"]:
        ids, incluir = por_categoria.get(c["categoria"], (c["usuarios_ids"], c["incluir_responsavel"]))
        cats.append({"categoria": c["categoria"], "usuarios_ids": ids, "incluir_responsavel": bool(incluir)})
    return cliente.put("/api/notificacoes/configuracao", headers=auth(token),
                       json={"categorias": cats, "email_ativo": True, "hora_inicio": "07:00"})


def ciclo(db, enviador=None, agora=DIA):
    r = svc.executar_ciclo(db, enviador, agora, usar_configurado=False)
    db.expire_all()
    return r


def test_somente_master_configura_e_regras_de_destinatario(cliente, token_master, equipe):
    tb = login(cliente, "bia", "Definitiva2026")
    assert cliente.get("/api/notificacoes/configuracao", headers=auth(tb)).status_code == 403
    cfg = cliente.get("/api/notificacoes/configuracao", headers=auth(token_master)).json()
    assert {c["categoria"] for c in cfg["categorias"]} >= {"audiencias", "reunioes", "financeiro"}
    # Quem não tem "Recebimento de notificações" não pode ser escolhido
    r = configurar(cliente, token_master, audiencias=([equipe["caio"]["id"]], True))
    assert r.status_code == 422 and "Recebimento de notificações" in r.json()["detail"]
    # Avisos financeiros só para quem tem Financeiro
    r = configurar(cliente, token_master, financeiro=([equipe["ana"]["id"]], False))
    assert r.status_code == 422 and "Financeiro" in r.json()["detail"]
    r = configurar(cliente, token_master, audiencias=([equipe["ana"]["id"], equipe["bia"]["id"]], False),
                   financeiro=([equipe["master"]["id"], equipe["bia"]["id"]], False))
    assert r.status_code == 200, r.text
    aud = next(c for c in r.json()["categorias"] if c["categoria"] == "audiencias")
    assert set(aud["usuarios_ids"]) == {equipe["ana"]["id"], equipe["bia"]["id"]} and aud["incluir_responsavel"] is False
    hist = cliente.get("/api/auditoria", headers=auth(token_master), params={"acao": "notificacoes.configuradas"})
    assert hist.status_code == 200


def test_avisos_da_agenda_para_todos_os_escolhidos_sem_duplicar(cliente, token_master, equipe, db):
    configurar(cliente, token_master, audiencias=([equipe["ana"]["id"], equipe["bia"]["id"]], True),
               ligacoes_retornos=([], True))
    novo(cliente, token_master, titulo="Audiência de instrução", tipo="audiencia", inicio=quando(1, 14),
         local="Fórum Criminal", responsavel_id=equipe["master"]["id"])
    novo(cliente, token_master, titulo="Ligar para o perito", tipo="ligacao", inicio=quando(0, 9),
         responsavel_id=equipe["ana"]["id"])
    falso = EnviadorFalso()
    r = ciclo(db, falso)
    # audiência: Ana, Bia e a Master (responsável); ligação: só a Ana (responsável)
    assert r.geradas == 4 and r.enviadas == 4
    assistentes = sorted(m.para for m in falso.enviados)
    assert assistentes == sorted([equipe["ana"]["email"], equipe["bia"]["email"], equipe["master"]["email"],
                                  equipe["ana"]["email"]])
    msg = next(m for m in falso.enviados if "AUDIÊNCIA" in m.assunto)
    assert msg.assunto == "[Advoga Fácil] AMANHÃ TEM AUDIÊNCIA" and "Fórum Criminal" in msg.texto
    # Rodar de novo não duplica nada
    r = ciclo(db, falso)
    assert r.geradas == 0 and r.enviadas == 0 and len(falso.enviados) == 4
    # Avisos no aplicativo da Ana
    ta = login(cliente, "ana", "Definitiva2026")
    minhas = cliente.get("/api/notificacoes/minhas", headers=auth(ta)).json()
    assert minhas["nao_lidas"] == 2 and {n["titulo"] for n in minhas["itens"]} == {
        "AMANHÃ TEM AUDIÊNCIA", "VOCÊ TEM UMA LIGAÇÃO PENDENTE"}
    r = cliente.post("/api/notificacoes/lidas", headers=auth(ta), json={"ids": [minhas["itens"][0]["id"]]})
    assert r.json()["marcadas"] == 1
    assert cliente.get("/api/notificacoes/minhas", headers=auth(ta)).json()["nao_lidas"] == 1
    cliente.post("/api/notificacoes/lidas", headers=auth(ta), json={})
    assert cliente.get("/api/notificacoes/minhas", headers=auth(ta),
                       params={"somente_nao_lidas": True}).json()["total"] == 0


def test_reagendar_ou_concluir_interrompe_o_aviso(cliente, token_master, equipe, db):
    configurar(cliente, token_master, reunioes=([equipe["ana"]["id"]], False))
    c = novo(cliente, token_master, titulo="Reunião", tipo="reuniao", inicio=quando(1, 10))
    assert ciclo(db, None).geradas == 1  # sem serviço de envio: aviso fica no app, e-mail "não configurado"
    linhas = cliente.get("/api/notificacoes/historico", headers=auth(token_master)).json()["itens"]
    assert linhas[0]["email_situacao"] == "nao_configurado"
    # Reagendado: o aviso antigo não vale mais; o novo dia gera novo aviso só quando for "hoje/amanhã"
    configurar(cliente, token_master, reunioes=([equipe["ana"]["id"], equipe["bia"]["id"]], False))
    r = cliente.post(f"/api/agenda/compromissos/{c['id']}/reagendar", headers=auth(token_master),
                     json={"versao": c["versao"], "inicio": quando(1, 16)})
    assert r.status_code == 200
    falso = EnviadorFalso()
    # gera para Ana e Bia (novo horário); o aviso da Bia é concluído antes do envio? Concluir agora:
    rr = svc.gerar(db, DIA)
    db.commit()
    assert rr == 2
    c = r.json()
    cliente.post(f"/api/agenda/compromissos/{c['id']}/concluir", headers=auth(token_master), json={"versao": c["versao"]})
    r = ciclo(db, falso)
    assert falso.enviados == [] and r.nao_enviadas == 2
    hist = cliente.get("/api/notificacoes/historico", headers=auth(token_master),
                       params={"situacao": "cancelado"}).json()
    assert hist["total"] == 2 and all("deixou de valer" in n["email_erro"] for n in hist["itens"])


def test_avisos_financeiros_param_quando_paga_e_sigilo(cliente, token_master, equipe, db, master):
    cli = cliente.post("/api/clientes", headers=auth(token_master), json={"nome_completo": "Cliente Aviso"}).json()
    c = contrato(cliente, token_master, cli["id"], valor_entrada="1000.00",
                 vencimento_entrada=(HOJE + timedelta(days=1)).isoformat())
    configurar(cliente, token_master, financeiro=([equipe["bia"]["id"]], False),
               audiencias=([equipe["ana"]["id"]], False))
    falso = EnviadorFalso()
    r = ciclo(db, falso)
    assert r.geradas == 1 and len(falso.enviados) == 1
    m = falso.enviados[0]
    assert m.para == equipe["bia"]["email"] and m.assunto == "[Advoga Fácil] AMANHÃ TEM PAGAMENTO"
    assert "R$" not in m.texto and "1000" not in m.texto and "Cliente Aviso" in m.texto
    # Ana (sem Financeiro) não recebe nada; e o histórico dela não mostra avisos financeiros
    ta = login(cliente, "ana", "Definitiva2026")
    assert cliente.get("/api/notificacoes/minhas", headers=auth(ta)).json()["total"] == 0
    # Paga antes do dia: o aviso de "vence hoje" não é gerado
    entrada = c["parcelas"][0]
    assert pagar(cliente, token_master, entrada["id"], "1000.00").status_code == 201
    amanha = DIA + timedelta(days=1)
    assert ciclo(db, falso, amanha).geradas == 0
    # Bia perde a permissão Financeiro: deixa de ver os avisos financeiros antigos
    u = cliente.get(f"/api/usuarios/{equipe['bia']['id']}", headers=auth(token_master)).json()
    r = cliente.put(f"/api/usuarios/{equipe['bia']['id']}/permissoes", headers=auth(token_master),
                    json={"permissoes": ["pendencias", "notificacoes"]})
    assert r.status_code == 200, r.text
    tb = login(cliente, "bia", "Definitiva2026")
    assert cliente.get("/api/notificacoes/minhas", headers=auth(tb)).json()["total"] == 0
    assert u["nome_usuario"] == "bia"


def test_falhas_de_envio_tentativas_e_reenvio(cliente, token_master, equipe, db):
    configurar(cliente, token_master, prazos=([equipe["ana"]["id"]], False))
    novo(cliente, token_master, titulo="Prazo de memoriais", tipo="prazo", inicio=quando(0), dia_inteiro=True)
    temporaria = EnviadorFalso(ErroEnvio("Servidor de e-mail indisponível", temporaria=True))
    r = ciclo(db, temporaria)
    assert r.falhas == 1
    n = cliente.get("/api/notificacoes/historico", headers=auth(token_master)).json()["itens"][0]
    assert n["email_situacao"] == "pendente" and n["email_tentativas"] == 1 and "indisponível" in n["email_erro"]
    # Antes do tempo de nova tentativa, não tenta de novo
    assert ciclo(db, temporaria, DIA + timedelta(minutes=1)).falhas == 0
    t = DIA
    for _ in range(4):
        t += timedelta(hours=1)
        ciclo(db, temporaria, t)
    n = cliente.get("/api/notificacoes/historico", headers=auth(token_master)).json()["itens"][0]
    assert n["email_situacao"] == "falhou" and n["email_tentativas"] == svc.MAX_TENTATIVAS
    # Reenvio manual pela Master
    r = cliente.post(f"/api/notificacoes/{n['id']}/reenviar", headers=auth(token_master))
    assert r.status_code == 200 and r.json()["email_situacao"] == "pendente"
    ok = EnviadorFalso()
    ciclo(db, ok, t)
    n = cliente.get("/api/notificacoes/historico", headers=auth(token_master)).json()["itens"][0]
    assert n["email_situacao"] == "enviado" and len(ok.enviados) == 1
    # Rejeição definitiva (endereço inválido) não é repetida
    novo(cliente, token_master, titulo="Outro prazo", tipo="prazo", inicio=quando(1), dia_inteiro=True)
    rej = EnviadorFalso(ErroEnvio("Endereço de destino recusado", temporaria=False))
    ciclo(db, rej, t)
    rejeitado = cliente.get("/api/notificacoes/historico", headers=auth(token_master),
                            params={"situacao": "rejeitado"}).json()["itens"]
    assert len(rejeitado) == 1 and "recusado" in rejeitado[0]["email_erro"]
    r = cliente.post(f"/api/notificacoes/{n['id']}/reenviar", headers=auth(token_master))
    assert r.status_code == 409


def test_horario_de_inicio_e_email_desligado(cliente, token_master, equipe, db):
    configurar(cliente, token_master, reunioes=([equipe["ana"]["id"]], False))
    novo(cliente, token_master, titulo="Reunião", tipo="reuniao", inicio=quando(1, 10))
    madrugada = datetime.combine(HOJE, time(5, 0)).astimezone()
    assert ciclo(db, EnviadorFalso(), madrugada).geradas == 0
    atual = cliente.get("/api/notificacoes/configuracao", headers=auth(token_master)).json()
    cats = [{"categoria": c["categoria"], "usuarios_ids": c["usuarios_ids"],
             "incluir_responsavel": bool(c["incluir_responsavel"])} for c in atual["categorias"]]
    r = cliente.put("/api/notificacoes/configuracao", headers=auth(token_master),
                    json={"categorias": cats, "email_ativo": False, "hora_inicio": "04:30"})
    assert r.status_code == 200 and not r.json()["email_ativo"]
    falso = EnviadorFalso()
    assert ciclo(db, falso, madrugada).geradas == 1 and falso.enviados == []
    n = cliente.get("/api/notificacoes/historico", headers=auth(token_master)).json()["itens"][0]
    assert n["email_situacao"] == "desativado"
    r = cliente.put("/api/notificacoes/configuracao", headers=auth(token_master),
                    json={"categorias": cats, "email_ativo": True, "hora_inicio": "25:00"})
    assert r.status_code == 422


def test_historico_nao_e_apagado_e_verificar_agora(cliente, token_master, equipe, db, url_banco):
    configurar(cliente, token_master, reunioes=([equipe["ana"]["id"]], False))
    novo(cliente, token_master, titulo="Reunião", tipo="reuniao", inicio=quando(1, 10))
    r = cliente.post("/api/notificacoes/verificar-agora", headers=auth(token_master))
    assert r.status_code == 200
    ta = login(cliente, "ana", "Definitiva2026")
    assert cliente.post("/api/notificacoes/verificar-agora", headers=auth(ta)).status_code == 403
    assert cliente.get("/api/notificacoes/historico", headers=auth(ta)).status_code == 403
    ciclo(db, None)  # garante pelo menos um aviso, qualquer que seja a hora em que o teste roda
    assert cliente.get("/api/notificacoes/historico", headers=auth(token_master)).json()["total"] == 1
    eng = create_engine(url_banco)
    with pytest.raises(DBAPIError):
        with eng.begin() as con:
            con.execute(text("DELETE FROM notificacoes"))
    eng.dispose()
