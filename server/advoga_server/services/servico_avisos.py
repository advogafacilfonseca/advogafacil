"""Serviço de avisos que roda dentro do servidor, em segundo plano.

Funciona mesmo com todos os aplicativos fechados: a cada intervalo gera os avisos novos e envia
os e-mails pendentes. Se houver mais de um processo do servidor, a trava no banco garante que só
um ciclo rode por vez.
"""

from __future__ import annotations

import logging
import threading

from ..core.db import obter_sessao

log = logging.getLogger("advoga.servico_avisos")


class ServicoAvisos:
    def __init__(self, intervalo_segundos: int, cfg=None) -> None:
        self.cfg = cfg
        self.intervalo = max(30, intervalo_segundos)
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None

    def iniciar(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._parar.clear()
        self._thread = threading.Thread(target=self._laco, name="servico-avisos", daemon=True)
        self._thread.start()
        log.info("Serviço de avisos iniciado (a cada %s segundos).", self.intervalo)

    def parar(self) -> None:
        self._parar.set()
        if self._thread:
            self._thread.join(timeout=30)

    def _laco(self) -> None:
        # Primeira verificação logo após o servidor iniciar (com pequena espera para o banco).
        if self._parar.wait(10):
            return
        while not self._parar.is_set():
            self.executar_uma_vez()
            self._parar.wait(self.intervalo)

    def executar_uma_vez(self) -> None:
        from . import notificacoes

        gerador = obter_sessao()
        db = next(gerador)
        try:
            r = notificacoes.executar_ciclo(db, cfg=self.cfg)
            if r and (r.geradas or r.enviadas or r.falhas):
                log.info("Avisos: %s gerados, %s e-mails enviados, %s falhas.", r.geradas, r.enviadas, r.falhas)
        except Exception:  # noqa: BLE001 - o serviço não pode parar por um erro pontual
            log.exception("Erro no ciclo do serviço de avisos")
        finally:
            gerador.close()
