from __future__ import annotations
from src.page_context import detect_document_scale, marcas_monetarias

falhas=0

def checa(rotulo: str, obtido, esperado)->None:
    global falhas
    ok = obtido == esperado
    if not ok:
        falhas+=1
    print(f"{'OK ' if ok else 'FALHA'} {rotulo}")
    if not ok:
        print(f" esperado={esperado} obtido={obtido}")

COPASA_P1="""Belo Horizonte, 08 de maio de 2026 - A COPASA MG (B3: CSMG3) anuncia hoje o resultado
do primeiro trimestre de 2026 (1T26). As informacoes financeiras, exceto quando indicado de
outra forma, sao apresentadas em milhares de reais (R$ mil) e se referem a Controladora e a
Consolidado.
- Volume de agua de 170 milhoes m3 (-0,4%) | Esgoto 118 milhoes m3 (+0,3%)
- Receita liquida de R$1,9bi (+2,5%)
- EBITDA de R$787 milhoes (-3,2%) | Margem de 40,9% (-240bps)
- Lucro liquido de R$368 milhoes (-14,1%)
"""

checa("COPASA p1: escolhe 'mil' da nota, nao 'milhoes' dos destaques",
      detect_document_scale([COPASA_P1]), ("mil", "BRL"))

checa("qualificador e escala em LINHAS diferentes ainda casam",
      detect_document_scale(["As informacoes, exceto quando indicado de\noutra forma, "
      "sao apresentadas em milhares de reais. "]),
      ("mil", "BRL"))

checa("legenda de tabela sozinha NAO vira padrao do documento",
      detect_document_scale(["Desempenho Financeiro\nR$ milhoes\nReceita 1.234"]),
      (None, None))

checa("valor citado em prosa, sem qualificador, NAO vira padrao",
      detect_document_scale(["O lucro liquido totalizou R$ 368 milhoes no trimestre."]),
      (None, None))

checa("duas notas globais em conflito desativam a heranca",
      detect_document_scale([
          "Os valores estao expressos em milhares de reais.",
          "Todos os valores sao apresentados em R$ milhoes.",
      ]),
      (None, None))

checa("nota fora das 3 primeiras paginas e ignorada",
      detect_document_scale(["", "", "", "Todos os valores sao apresentados em R$ mil."]),
      (None, None))

checa("documento sem nota nenhuma",
      detect_document_scale(["Release de Resultados 1T26", "Receita 1.380.100"]),
      (None, None))

checa("tabela operacional NAO e monetaria (COPASA p3)",
      marcas_monetarias([
          "Ligacoes (1.000 unidades) 4.690 4.619 1,5%\n"
          "Volume Distribuido (1.000 m3) 284.045 285.189 -0,4%\n"
          "Extensao de Rede (km) 66.579 65.147 2,2%"
      ])[0],
      False)

checa("tabela de receita E monetaria (COPASA p8)",
      marcas_monetarias([
          "Receita Bruta - Agua 1.380.100 1.357.411 1,7%\n"
          "Receita Bruta - Esgoto 723.761 694.315 4,2%"
      ])[0],
      True)

checa("tabela de tarifa (R$/m3) fica FORA: unidade por coluna",
      marcas_monetarias([
          "Categoria 1T26 1T25\nTarifa media (R$/m3) 4,31 4,21\nResidencial 949 939"
      ])[0],
      False)

checa("balanco patrimonial e monetario",
      marcas_monetarias(["ATIVO - CONTROLADORA 03/2026\nCaixa e equivalentes 3.540.240"])[0],
      True)

checa("tabela vazia nao e monetaria",
      marcas_monetarias([])[0],False)

print()
print("TODOS OS TESTES PASSARAM" if falhas==0 else f"{falhas} FALHA(S)")
raise SystemExit(1 if falhas else 0)