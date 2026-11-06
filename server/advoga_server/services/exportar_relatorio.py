"""Exportação dos relatórios em PDF (reportlab) e Excel (openpyxl).

O arquivo é montado no servidor a partir do relatório já filtrado pelas permissões:
o que não pode ser visto não chega a entrar no arquivo.
"""

from __future__ import annotations

import io
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from advoga_shared.esquemas import Relatorio

from .financeiro import reais

LOGO = Path(__file__).resolve().parents[1] / "recursos" / "logo-relatorio.png"
DOURADO = "#C9A24A"
GRAFITE = "#141414"


def texto_celula(valor, tipo: str) -> str:
    if valor is None or valor == "":
        return ""
    if tipo == "valor":
        return reais(Decimal(valor))
    if isinstance(valor, datetime):
        return valor.astimezone().strftime("%d/%m/%Y %H:%M")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    return str(valor)


# =================================================================================== PDF
def pdf(rel: Relatorio) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    largura_pag, altura_pag = landscape(A4)
    margem = 1.2 * cm
    faixa = 2.3 * cm
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=margem, rightMargin=margem,
                            topMargin=faixa + 0.6 * cm, bottomMargin=1.4 * cm, title=rel.titulo,
                            author="Advoga Fácil", subject=rel.titulo, creator="Advoga Fácil")
    gerado = rel.gerado_em.astimezone().strftime("%d/%m/%Y às %H:%M")

    def moldura(canvas, _doc) -> None:
        canvas.saveState()
        canvas.setFillColor(colors.HexColor(GRAFITE))
        canvas.rect(0, altura_pag - faixa, largura_pag, faixa, stroke=0, fill=1)
        canvas.setFillColor(colors.HexColor(DOURADO))
        canvas.rect(0, altura_pag - faixa - 2, largura_pag, 2, stroke=0, fill=1)
        x = margem
        if LOGO.exists():
            from reportlab.lib.utils import ImageReader

            img = ImageReader(str(LOGO))
            lw, lh = img.getSize()
            h = faixa - 0.4 * cm
            canvas.drawImage(img, x, altura_pag - faixa + 0.2 * cm, width=h * lw / lh, height=h)
            x += h * lw / lh + 0.4 * cm
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 16)
        canvas.drawString(x, altura_pag - 1.05 * cm, rel.titulo)
        canvas.setFillColor(colors.HexColor(DOURADO))
        canvas.setFont("Helvetica", 9)
        canvas.drawString(x, altura_pag - 1.6 * cm, f"Gerado em {gerado} por {rel.gerado_por}")
        if rel.confidencial:
            canvas.setFont("Helvetica-Bold", 9)
            canvas.drawRightString(largura_pag - margem, altura_pag - 1.05 * cm, "CONFIDENCIAL")
            canvas.setFont("Helvetica", 8)
            canvas.drawRightString(largura_pag - margem, altura_pag - 1.5 * cm, "Contém informações financeiras")
        canvas.setFillColor(colors.HexColor("#555555"))
        canvas.setFont("Helvetica", 8)
        canvas.drawString(margem, 0.8 * cm, "Advoga Fácil · " + rel.titulo)
        canvas.drawRightString(largura_pag - margem, 0.8 * cm, f"Página {canvas.getPageNumber()}")
        canvas.restoreState()

    base = ParagraphStyle("base", fontName="Helvetica", fontSize=7.5, leading=9.2)
    direita = ParagraphStyle("dir", parent=base, alignment=TA_RIGHT)
    cab = ParagraphStyle("cab", parent=base, fontName="Helvetica-Bold", textColor=colors.white)
    cab_dir = ParagraphStyle("cabdir", parent=cab, alignment=TA_RIGHT)
    info = ParagraphStyle("info", parent=base, fontSize=8.5, leading=11, textColor=colors.HexColor("#333333"))

    def esc(t: str) -> str:
        return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    historia = [Paragraph(esc("  ·  ".join(rel.filtros)), info)]
    if rel.observacao:
        historia.append(Paragraph(esc(rel.observacao), info))
    historia.append(Spacer(1, 0.3 * cm))

    util = largura_pag - 2 * margem
    pesos = [max(c.largura, 1) for c in rel.colunas]
    larguras = [util * p / sum(pesos) for p in pesos]
    dados = [[Paragraph(esc(c.titulo), cab_dir if c.tipo in ("valor", "numero") else cab) for c in rel.colunas]]
    for linha in rel.linhas:
        dados.append([Paragraph(esc(texto_celula(v, c.tipo)), direita if c.tipo in ("valor", "numero") else base)
                      for v, c in zip(linha, rel.colunas)])
    if not rel.linhas:
        dados.append([Paragraph("Nenhum registro encontrado com estes filtros.", base)] + [""] * (len(rel.colunas) - 1))
    tabela = LongTable(dados, colWidths=larguras, repeatRows=1)
    estilo = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(GRAFITE)),
              ("LINEBELOW", (0, 0), (-1, 0), 1.2, colors.HexColor(DOURADO)),
              ("VALIGN", (0, 0), (-1, -1), "TOP"),
              ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
              ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#DDDDDD"))]
    for i in range(2, len(dados), 2):
        estilo.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F6F3EC")))
    if not rel.linhas:
        estilo.append(("SPAN", (0, 1), (-1, 1)))
    tabela.setStyle(TableStyle(estilo))
    historia.append(tabela)

    if rel.totais:
        historia.append(Spacer(1, 0.4 * cm))
        tot = Table([[Paragraph(esc(t.rotulo), base), Paragraph(f"<b>{esc(t.valor)}</b>", direita)]
                     for t in rel.totais], colWidths=[7 * cm, 4 * cm], hAlign="RIGHT")
        tot.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 1, colors.HexColor(DOURADO)),
                                 ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        historia.append(tot)
    doc.build(historia, onFirstPage=moldura, onLaterPages=moldura)
    return buf.getvalue()


# ================================================================================= Excel
def xlsx(rel: Relatorio) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = rel.titulo[:31]
    gerado = rel.gerado_em.astimezone().strftime("%d/%m/%Y %H:%M")
    ws["A1"] = rel.titulo
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"Gerado em {gerado} por {rel.gerado_por}"
    ws["A3"] = " · ".join(rel.filtros)
    linha = 4
    if rel.confidencial:
        ws.cell(linha, 1, "CONFIDENCIAL: contém informações financeiras").font = Font(bold=True, color="9C6500")
        linha += 1
    if rel.observacao:
        ws.cell(linha, 1, rel.observacao).font = Font(italic=True, color="555555")
        linha += 1
    linha += 1
    cabecalho = linha
    preenchimento = PatternFill("solid", fgColor="141414")
    borda = Border(bottom=Side(style="medium", color="C9A24A"))
    for j, c in enumerate(rel.colunas, start=1):
        cel = ws.cell(cabecalho, j, c.titulo)
        cel.font = Font(bold=True, color="FFFFFF")
        cel.fill = preenchimento
        cel.border = borda
        cel.alignment = Alignment(horizontal="right" if c.tipo in ("valor", "numero") else "left", vertical="center")
    larguras = [len(c.titulo) for c in rel.colunas]
    for i, dados in enumerate(rel.linhas, start=cabecalho + 1):
        for j, (v, c) in enumerate(zip(dados, rel.colunas), start=1):
            if c.tipo == "valor" and v is not None:
                cel = ws.cell(i, j, Decimal(v))
                cel.number_format = '"R$" #,##0.00;[Red]-"R$" #,##0.00'
                larguras[j - 1] = max(larguras[j - 1], 14)
                continue
            if isinstance(v, datetime):
                cel = ws.cell(i, j, v.astimezone().replace(tzinfo=None))
                cel.number_format = "DD/MM/YYYY HH:MM"
                larguras[j - 1] = max(larguras[j - 1], 16)
                continue
            if isinstance(v, date):
                cel = ws.cell(i, j, v)
                cel.number_format = "DD/MM/YYYY"
                larguras[j - 1] = max(larguras[j - 1], 11)
                continue
            ws.cell(i, j, v)
            larguras[j - 1] = max(larguras[j - 1], min(len(str(v)) if v is not None else 0, 60))
    for j, w in enumerate(larguras, start=1):
        ws.column_dimensions[get_column_letter(j)].width = w + 2
    fim = cabecalho + max(len(rel.linhas), 1)
    if rel.colunas:
        ws.auto_filter.ref = f"A{cabecalho}:{get_column_letter(len(rel.colunas))}{fim}"
    ws.freeze_panes = ws.cell(cabecalho + 1, 1)
    if not rel.linhas:
        ws.cell(cabecalho + 1, 1, "Nenhum registro encontrado com estes filtros.")
    if rel.totais:
        t = ws if len(rel.totais) <= 4 else wb.create_sheet("Totais")
        inicio = fim + 2 if t is ws else 1
        for k, tot in enumerate(rel.totais):
            t.cell(inicio + k, 1, tot.rotulo).font = Font(bold=True)
            t.cell(inicio + k, 2, tot.valor)
        if t is not ws:
            t.column_dimensions["A"].width = 42
            t.column_dimensions["B"].width = 22
    ws.oddFooter.center.text = "Página &P de &N"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToHeight = 0
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
