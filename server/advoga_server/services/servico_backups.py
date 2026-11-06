"""Serviço da Central de Backups que roda dentro do servidor, em segundo plano.

A cada minuto confere se há um backup (rápido ou completo) ou um teste de restauração a fazer,
conforme a configuração da Master, e verifica se o HD de backup está conectado.
"""

from __future__ import annotations

import logging
import threading

from ..core.db import obter_sessao

log = logging.getLogger("advoga.servico_backups")


class ServicoBackups:
    def __init__(self, cfg, intervalo_segundos: int = 60) -> None:
        self.cfg = cfg
        self.intervalo = max(15, intervalo_segundos)
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self._ultima_verificacao_destino = 0.0

    def iniciar(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._parar.clear()
        self._thread = threading.Thread(target=self._laco, name="servico-backups", daemon=True)
        self._thread.start()
        log.info("Serviço de backups iniciado.")

    def parar(self) -> None:
        self._parar.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _laco(self) -> None:
        if self._parar.wait(30):
            return
        while not self._parar.is_set():
            self.executar_uma_vez()
            self._parar.wait(self.intervalo)

    def executar_uma_vez(self) -> str | None:
        import time

        from fastapi import HTTPException

        from . import backup

        gerador = obter_sessao()
        db = next(gerador)
        try:
            if time.monotonic() - self._ultima_verificacao_destino > 3600:
                self._ultima_verificacao_destino = time.monotonic()
                backup.verificar_destino_periodicamente(db)
            tarefa = backup.tarefa_devida(db)
            if tarefa == "teste_restauracao":
                e = backup.testar_restauracao(db, self.cfg)
            elif tarefa:
                e = backup.executar(db, self.cfg, tarefa)
            else:
                return None
            log.info("Backup automático (%s): %s. %s", tarefa, e.situacao, e.mensagem)
            return tarefa
        except HTTPException:  # já existe um backup em andamento
            return None
        except Exception:  # noqa: BLE001 - o serviço não pode parar por um erro pontual
            log.exception("Erro no serviço de backups")
            return None
        finally:
            gerador.close()
