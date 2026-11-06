"""Gerenciamento de Usuários e Permissões.

A tela apenas reflete as regras: todas as verificações acontecem no servidor.
"""

from __future__ import annotations

import secrets

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from advoga_shared.esquemas import UsuarioDetalhe
from advoga_shared.permissoes import ROTULOS_PERMISSAO, Permissao

from ...api_client.cliente import ClienteAPI, ErroAPI
from ..componentes.basicos import ajustar_altura, bloco_campo, campo, cartao, rotulo
from ..componentes.espera import cursor_espera
from ..componentes.formatos import data_hora_br


def gerar_senha_provisoria() -> str:
    alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz"
    return "".join(secrets.choice(alfabeto) for _ in range(8)) + "".join(
        secrets.choice("23456789") for _ in range(4))


class _CaixasPermissao(QWidget):
    def __init__(self) -> None:
        super().__init__()
        grade = QGridLayout(self)
        grade.setContentsMargins(0, 0, 0, 0)
        self.caixas: dict[Permissao, QCheckBox] = {}
        for i, p in enumerate(Permissao):
            c = QCheckBox(ROTULOS_PERMISSAO[p])
            self.caixas[p] = c
            grade.addWidget(c, i // 2, i % 2)

    def definir(self, permissoes: list[Permissao]) -> None:
        for p, c in self.caixas.items():
            c.setChecked(p in permissoes)

    def selecionadas(self) -> list[str]:
        return [p.value for p, c in self.caixas.items() if c.isChecked()]

    def habilitar(self, sim: bool) -> None:
        for c in self.caixas.values():
            c.setEnabled(sim)


class DialogoNovoUsuario(QDialog):
    def __init__(self, api: ClienteAPI, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self.criado: UsuarioDetalhe | None = None
        self.setWindowTitle("Novo usuário")
        self.setMinimumWidth(620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 20, 28, 20)
        lay.addWidget(rotulo("Cadastrar usuário", "secao"))
        self.nome = campo("Nome completo", maximo=150)
        self.exibicao = campo("Como o nome aparece no sistema", maximo=80)
        self.cargo = campo("Ex.: Advogado associado, Secretária", maximo=80)
        self.usuario = campo("ex.: joao.silva", maximo=40)
        self.email = campo("E-mail para receber notificações", maximo=254)
        self.senha = campo(maximo=128)
        self.senha.setText(gerar_senha_provisoria())
        gerar = QPushButton("Gerar outra")
        gerar.clicked.connect(lambda: self.senha.setText(gerar_senha_provisoria()))
        g = QGridLayout()
        g.addWidget(bloco_campo("Nome completo", self.nome), 0, 0, 1, 2)
        g.addWidget(bloco_campo("Nome de exibição", self.exibicao), 1, 0)
        g.addWidget(bloco_campo("Cargo (apenas informativo)", self.cargo), 1, 1)
        g.addWidget(bloco_campo("Nome de usuário", self.usuario), 2, 0)
        g.addWidget(bloco_campo("E-mail", self.email), 2, 1)
        linha_senha = QHBoxLayout()
        linha_senha.addWidget(bloco_campo("Senha provisória (o usuário troca no primeiro acesso)", self.senha), 1)
        linha_senha.addWidget(gerar, 0, Qt.AlignmentFlag.AlignBottom)
        lay.addLayout(g)
        lay.addLayout(linha_senha)
        self.permissoes = _CaixasPermissao()
        if api.usuario and api.usuario.is_master:
            lay.addWidget(rotulo("Permissões", "rotuloCampo"))
            lay.addWidget(self.permissoes)
        else:
            lay.addWidget(rotulo("O usuário será criado sem permissões. Somente a Master pode concedê-las.",
                                 "rotuloCampo", True))
        self.erro = rotulo("", "erro", True)
        lay.addWidget(self.erro)
        b = QHBoxLayout()
        cancelar = QPushButton("Cancelar")
        self.btn_salvar = QPushButton("Cadastrar")
        self.btn_salvar.setObjectName("primario")
        b.addWidget(cancelar)
        b.addStretch()
        b.addWidget(self.btn_salvar)
        lay.addLayout(b)
        cancelar.clicked.connect(self.reject)
        self.btn_salvar.clicked.connect(self.salvar)
        ajustar_altura(self)

    def salvar(self) -> None:
        dados = {
            "nome_completo": self.nome.text().strip(),
            "nome_exibicao": self.exibicao.text().strip() or None,
            "cargo": self.cargo.text().strip() or None,
            "nome_usuario": self.usuario.text().strip(),
            "email": self.email.text().strip(),
            "senha_provisoria": self.senha.text(),
            "permissoes": self.permissoes.selecionadas() if self.api.usuario.is_master else [],
        }
        if not dados["nome_completo"] or not dados["nome_usuario"] or not dados["email"]:
            self.erro.setText("Preencha nome completo, nome de usuário e e-mail.")
            ajustar_altura(self)
            return
        try:
            with cursor_espera():
                self.criado = self.api.criar_usuario(dados)
        except ErroAPI as exc:
            self.erro.setText(exc.mensagem)
            ajustar_altura(self)
            return
        QMessageBox.information(
            self, "Usuário cadastrado",
            f"{self.criado.nome_completo} foi cadastrado(a).\n\nUsuário: {self.criado.nome_usuario}\n"
            f"Senha provisória: {dados['senha_provisoria']}\n\nInforme a senha pessoalmente. "
            "Ela será trocada no primeiro acesso.")
        self.accept()


class TelaUsuarios(QWidget):
    COLUNAS = ["Nome", "Usuário", "Cargo", "Situação", "Último acesso"]

    def __init__(self, api: ClienteAPI) -> None:
        super().__init__()
        self.api = api
        self.usuarios: list[UsuarioDetalhe] = []
        self.atual: UsuarioDetalhe | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        topo = QHBoxLayout()
        topo.addWidget(rotulo("Usuários e Permissões", "titulo"))
        topo.addStretch()
        self.btn_atualizar = QPushButton("Atualizar lista")
        self.btn_novo = QPushButton("Novo usuário")
        self.btn_novo.setObjectName("primario")
        topo.addWidget(self.btn_atualizar)
        topo.addWidget(self.btn_novo)
        lay.addLayout(topo)

        divisor = QSplitter(Qt.Orientation.Horizontal)
        self.tabela = QTableWidget(0, len(self.COLUNAS))
        self.tabela.setHorizontalHeaderLabels(self.COLUNAS)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabela.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        divisor.addWidget(self.tabela)

        # Painel de detalhes
        self.detalhe = cartao()
        ld = QVBoxLayout(self.detalhe)
        ld.setContentsMargins(20, 16, 20, 16)
        self.titulo_detalhe = rotulo("Selecione um usuário", "secao")
        ld.addWidget(self.titulo_detalhe)
        self.info = rotulo("", "rotuloCampo")
        ld.addWidget(self.info)
        self.f_nome = campo(maximo=150)
        self.f_exibicao = campo(maximo=80)
        self.f_cargo = campo(maximo=80)
        self.f_email = campo(maximo=254)
        g = QGridLayout()
        g.addWidget(bloco_campo("Nome completo", self.f_nome), 0, 0, 1, 2)
        g.addWidget(bloco_campo("Nome de exibição", self.f_exibicao), 1, 0)
        g.addWidget(bloco_campo("Cargo (apenas informativo)", self.f_cargo), 1, 1)
        g.addWidget(bloco_campo("E-mail", self.f_email), 2, 0, 1, 2)
        ld.addLayout(g)
        self.btn_salvar_dados = QPushButton("Salvar dados")
        ld.addWidget(self.btn_salvar_dados, 0, Qt.AlignmentFlag.AlignRight)
        ld.addWidget(rotulo("Permissões", "secao"))
        self.aviso_perm = rotulo("", "rotuloCampo", True)
        ld.addWidget(self.aviso_perm)
        self.permissoes = _CaixasPermissao()
        ld.addWidget(self.permissoes)
        self.btn_salvar_perm = QPushButton("Salvar permissões")
        self.btn_salvar_perm.setObjectName("primario")
        ld.addWidget(self.btn_salvar_perm, 0, Qt.AlignmentFlag.AlignRight)
        acoes = QHBoxLayout()
        self.btn_senha = QPushButton("Redefinir senha")
        self.btn_situacao = QPushButton("Desativar usuário")
        acoes.addWidget(self.btn_senha)
        acoes.addStretch()
        acoes.addWidget(self.btn_situacao)
        ld.addLayout(acoes)
        ld.addStretch()
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setWidget(self.detalhe)
        divisor.addWidget(rolagem)
        divisor.setSizes([560, 520])
        lay.addWidget(divisor, 1)

        self.btn_atualizar.clicked.connect(self.carregar)
        self.btn_novo.clicked.connect(self.novo)
        self.tabela.itemSelectionChanged.connect(self._selecionar)
        self.btn_salvar_dados.clicked.connect(self.salvar_dados)
        self.btn_salvar_perm.clicked.connect(self.salvar_permissoes)
        self.btn_senha.clicked.connect(self.redefinir_senha)
        self.btn_situacao.clicked.connect(self.alternar_situacao)
        self._mostrar(None)

    # ---------------------------------------------------------------- dados
    def showEvent(self, evento) -> None:  # noqa: N802
        super().showEvent(evento)
        if not self.usuarios:
            self.carregar()

    def carregar(self, selecionar_id: str | None = None) -> None:
        try:
            with cursor_espera():
                self.usuarios = self.api.listar_usuarios()
        except ErroAPI as exc:
            QMessageBox.warning(self, "Usuários", exc.mensagem)
            return
        self.tabela.setRowCount(len(self.usuarios))
        for i, u in enumerate(self.usuarios):
            nome = u.nome_completo + ("  (Master)" if u.is_master else "")
            valores = [nome, u.nome_usuario, u.cargo or "—", "Ativo" if u.ativo else "Desativado",
                       data_hora_br(u.ultimo_login_em)]
            for j, v in enumerate(valores):
                item = QTableWidgetItem(v)
                if not u.ativo:
                    item.setForeground(Qt.GlobalColor.gray)
                self.tabela.setItem(i, j, item)
        self.tabela.resizeColumnsToContents()
        self.tabela.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        alvo = selecionar_id or (str(self.atual.id) if self.atual else None)
        if alvo:
            for i, u in enumerate(self.usuarios):
                if str(u.id) == alvo:
                    self.tabela.selectRow(i)
                    return
        self._mostrar(None)

    def _selecionar(self) -> None:
        linhas = self.tabela.selectionModel().selectedRows()
        self._mostrar(self.usuarios[linhas[0].row()] if linhas else None)

    def _mostrar(self, u: UsuarioDetalhe | None) -> None:
        self.atual = u
        eu = self.api.usuario
        tem = u is not None
        for w in (self.f_nome, self.f_exibicao, self.f_cargo, self.f_email, self.btn_salvar_dados,
                  self.btn_senha, self.btn_situacao, self.btn_salvar_perm):
            w.setEnabled(tem)
        if not tem:
            self.titulo_detalhe.setText("Selecione um usuário")
            self.info.setText("")
            for f in (self.f_nome, self.f_exibicao, self.f_cargo, self.f_email):
                f.clear()
            self.permissoes.definir([])
            self.permissoes.habilitar(False)
            self.aviso_perm.setText("")
            return
        self.titulo_detalhe.setText(u.nome_completo)
        linhas = [f"Usuário: {u.nome_usuario}  ·  {'Ativo' if u.ativo else 'Desativado'}"
                  f"  ·  Sessões abertas: {u.sessoes_ativas}",
                  f"Cadastrado em {data_hora_br(u.criado_em)}  ·  Último acesso: {data_hora_br(u.ultimo_login_em)}"]
        if u.deve_trocar_senha:
            linhas.append("Aguardando a troca da senha provisória no primeiro acesso.")
        self.info.setText("\n".join(linhas))
        self.f_nome.setText(u.nome_completo)
        self.f_exibicao.setText(u.nome_exibicao)
        self.f_cargo.setText(u.cargo or "")
        self.f_email.setText(u.email)
        self.permissoes.definir(u.permissoes)
        e_eu = str(u.id) == str(eu.id)
        pode_perm = eu.is_master and not u.is_master and not e_eu
        self.permissoes.habilitar(pode_perm)
        self.btn_salvar_perm.setEnabled(pode_perm)
        if u.is_master:
            self.aviso_perm.setText("A Master tem todas as permissões, que não podem ser alteradas.")
        elif e_eu:
            self.aviso_perm.setText("Ninguém pode alterar os próprios privilégios.")
        elif not eu.is_master:
            self.aviso_perm.setText("Somente a Master pode conceder ou retirar permissões.")
        else:
            self.aviso_perm.setText("Marque o que este usuário pode acessar. O cargo não concede permissões.")
        editavel = eu.is_master or not u.is_master
        for w in (self.f_nome, self.f_exibicao, self.f_cargo, self.f_email, self.btn_salvar_dados):
            w.setEnabled(editavel)
        self.btn_senha.setEnabled(not u.is_master and not e_eu)
        self.btn_situacao.setEnabled(not u.is_master and not e_eu)
        self.btn_situacao.setText("Reativar usuário" if not u.ativo else "Desativar usuário")

    # ---------------------------------------------------------------- ações
    def novo(self) -> None:
        dlg = DialogoNovoUsuario(self.api, self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.criado:
            self.carregar(str(dlg.criado.id))

    def _executar(self, func, sucesso: str) -> None:
        try:
            with cursor_espera():
                u = func()
        except ErroAPI as exc:
            QMessageBox.warning(self, "Usuários e Permissões", exc.mensagem)
            return
        self.carregar(str(u.id))
        janela = self.window()
        if hasattr(janela, "statusBar"):
            janela.statusBar().showMessage(sucesso, 6000)
        else:
            QMessageBox.information(self, "Usuários e Permissões", sucesso)

    def salvar_dados(self) -> None:
        u = self.atual
        dados = {"nome_completo": self.f_nome.text().strip(), "nome_exibicao": self.f_exibicao.text().strip(),
                 "cargo": self.f_cargo.text().strip() or None, "email": self.f_email.text().strip()}
        self._executar(lambda: self.api.atualizar_usuario(str(u.id), dados), "Dados do usuário salvos.")

    def salvar_permissoes(self) -> None:
        u = self.atual
        sel = self.permissoes.selecionadas()
        if QMessageBox.question(self, "Confirmar permissões",
                                f"Salvar as permissões de {u.nome_completo}?") != QMessageBox.StandardButton.Yes:
            return
        self._executar(lambda: self.api.definir_permissoes(str(u.id), sel), "Permissões salvas.")

    def redefinir_senha(self) -> None:
        u = self.atual
        senha = gerar_senha_provisoria()
        if QMessageBox.question(
            self, "Redefinir senha",
            f"Gerar uma nova senha provisória para {u.nome_completo}?\n"
            "As sessões abertas desse usuário serão encerradas.") != QMessageBox.StandardButton.Yes:
            return
        try:
            with cursor_espera():
                self.api.redefinir_senha_usuario(str(u.id), senha)
        except ErroAPI as exc:
            QMessageBox.warning(self, "Redefinir senha", exc.mensagem)
            return
        QMessageBox.information(self, "Senha redefinida",
                                f"Nova senha provisória de {u.nome_usuario}:\n\n{senha}\n\n"
                                "Informe-a pessoalmente. Ela será trocada no próximo acesso.")
        self.carregar(str(u.id))

    def alternar_situacao(self) -> None:
        u = self.atual
        ativar = not u.ativo
        texto = (f"Reativar o acesso de {u.nome_completo}?" if ativar else
                 f"Desativar {u.nome_completo}?\n\nO acesso é bloqueado na hora e as sessões abertas são "
                 "encerradas. Todo o histórico de atividades é preservado.")
        if QMessageBox.question(self, "Confirmar", texto) != QMessageBox.StandardButton.Yes:
            return
        self._executar(lambda: self.api.alterar_situacao_usuario(str(u.id), ativar),
                       "Usuário reativado." if ativar else "Usuário desativado.")
