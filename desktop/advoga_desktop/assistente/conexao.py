"""Configuração do endereço do servidor neste computador."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QVBoxLayout

from ..api_client.cliente import ClienteAPI, ErroAPI, impressao_digital, obter_certificado_servidor
from ..config_local import ConfigLocal, normalizar_endereco
from ..ui.componentes.basicos import ajustar_altura, bloco_campo, campo, logotipo, rotulo
from ..ui.componentes.espera import cursor_espera


class DialogoConexao(QDialog):
    def __init__(self, config: ConfigLocal, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Advoga Fácil — Conexão com o servidor")
        self.setMinimumWidth(520)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.setSpacing(12)
        lay.addWidget(logotipo(260))
        lay.addWidget(rotulo("Conexão com o servidor", "titulo"))
        lay.addWidget(rotulo(
            "Informe o endereço do computador servidor do escritório. No próprio servidor, use "
            "127.0.0.1. Nos demais computadores, use o nome ou endereço do servidor na rede "
            "local ou na Tailscale.", "subtitulo", quebra=True))

        self.endereco = campo("Ex.: 127.0.0.1 ou servidor-escritorio")
        self.endereco.setText(config.endereco_servidor.split("://")[-1] if config.endereco_servidor else "")
        lay.addWidget(bloco_campo("Endereço do servidor", self.endereco))

        self.resultado = rotulo("", quebra=True)
        lay.addWidget(self.resultado)

        botoes = QHBoxLayout()
        self.btn_testar = QPushButton("Testar conexão")
        self.btn_salvar = QPushButton("Salvar e continuar")
        self.btn_salvar.setObjectName("primario")
        self.btn_salvar.setEnabled(False)
        botoes.addWidget(self.btn_testar)
        botoes.addStretch()
        botoes.addWidget(self.btn_salvar)
        lay.addLayout(botoes)

        self.btn_testar.clicked.connect(self.testar)
        self.btn_salvar.clicked.connect(self.salvar)
        self.endereco.textChanged.connect(lambda: self.btn_salvar.setEnabled(False))
        self.endereco.returnPressed.connect(self.testar)
        self._endereco_testado = ""
        self._certificado = ""

        ajustar_altura(self)
    def testar(self) -> None:
        endereco = normalizar_endereco(self.endereco.text())
        if not endereco:
            self._mostrar("Informe o endereço do servidor.", ok=False)
            return
        certificado = ""
        try:
            with cursor_espera():
                if endereco.startswith("https://"):
                    certificado = obter_certificado_servidor(endereco)
                cliente = ClienteAPI(endereco, certificado, timeout=6)
                try:
                    saude = cliente.saude()
                finally:
                    cliente.fechar()
        except ErroAPI as exc:
            self._mostrar(exc.mensagem, ok=False)
            return
        if saude.servidor_status == "desativado":
            self._mostrar("Este servidor foi desativado após uma migração. Use o endereço do novo servidor.", ok=False)
            return
        estado = "configurado" if saude.configurado else "aguardando a configuração inicial"
        texto = f"Conectado ao servidor (versão {saude.versao}, banco de dados OK, {estado})."
        if certificado:
            texto += ("\n\nImpressão digital do certificado de segurança:\n"
                      f"{impressao_digital(certificado)}\n"
                      "Confira se é igual à do arquivo IMPRESSAO_DIGITAL.txt do servidor antes de salvar.")
        else:
            texto += "\n\nAtenção: conexão sem criptografia (http). Use apenas para testes."
        self._mostrar(texto, ok=True)
        self._endereco_testado = endereco
        self._certificado = certificado
        self.btn_salvar.setEnabled(True)

    def salvar(self) -> None:
        self.config.endereco_servidor = self._endereco_testado
        self.config.certificado_pem = self._certificado
        self.config.salvar()
        self.accept()

    def _mostrar(self, texto: str, ok: bool) -> None:
        self.resultado.setObjectName("sucesso" if ok else "erro")
        self.resultado.setText(texto)
        ajustar_altura(self)
        self.resultado.style().unpolish(self.resultado)
        self.resultado.style().polish(self.resultado)
