from __future__ import annotations
import csv
import logging
import sys
import os
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
import pdfplumber
from src.page_context import marcas_monetarias
from src.pdf_processor import (
    QUARTER_FROM_FILENAME,
    YEAR_FOLDER,
    discover_pdfs,
    extract_and_chunk,
    normalize_quarter,
    parse_metadata,
)
logger=logging.getLogger(__name__)
NULO="(nulo)"
EMPRESA_CONTROLE="Copel"

def _env(nome:str, padrao:str="")->str:
    return (os.getenv(nome) or padrao).strip()

def _env_int(nome:str, padrao:int)->int:
    bruto=_env(nome)
    return int(bruto) if bruto else padrao

def _motivo_descarte(pdf: Path, data_dir:Path)->str:
    try:
        partes=pdf.resolve().relative_to(data_dir.resolve()).parts
    except ValueError:
        return "fora do diretorio de dados"
    if len(partes)<3:
        return f"profundidade de pasta insuficiente (partes={len(partes)}, precisa >= 3)"
    if not YEAR_FOLDER.match(partes[1]):
        return f"pasta de ano invalida: {partes[1]!r}"
    achou_na_pasta=len(partes) >= 4 and normalize_quarter(partes[2]) is not None
    achou_no_nome=QUARTER_FROM_FILENAME.search(partes[-1]) is not None
    if not achou_na_pasta and not achou_no_nome:
        return "trimestre indeterminado (nem na pasta nem no nome do arquivo)"
    return "motivo nao identificado"

def varrer_caminhos(data_dir:Path):
    pdfs=discover_pdfs(data_dir)
    reconhecidos=[]
    descartados=[]
    log_pdf=logging.getLogger("src.pdf_processor")
    nivel_anterior=log_pdf.level
    log_pdf.setLevel(logging.ERROR)
    try:
        for pdf in pdfs:
            meta=parse_metadata(pdf, data_dir)
            if meta is None:
                descartados.append((pdf, _motivo_descarte(pdf, data_dir)))
            else:
                reconhecidos.append((pdf, meta))
    finally:
        log_pdf.setLevel(nivel_anterior)

    print("="*78)
    print(f"FASE 1 -- varredura de caminhos ({len(pdfs)} PDFs em {data_dir})")
    print("="*78)
    print(f"  reconhecidos: {len(reconhecidos)}")
    print(f"  descartados: {len(descartados)}")

    if descartados:
        print()
        print(" ATENCAO: estes arquivos NAO entrariam no corpus, e sem erro:")
        for pdf, motivo in descartados:
            print(f" - {pdf.name}")
            print(f" - {motivo}")
    por_empresa={}
    for _, meta in reconhecidos:
        por_empresa.setdefault(meta.company, Counter())[meta.doc_type] += 1
    print()
    print(f" {'empresa':<18} {'arquivos':>8} tipos de documento")
    for empresa in sorted(por_empresa):
        tipos=por_empresa[empresa]
        detalhe=", ".join(f"{t}={n}" for t, n in sorted(tipos.items()))
        print(f" {empresa:<18} {sum(tipos.values()):>8} {detalhe}")
    print()
    return reconhecidos, descartados

@dataclass
class Pagina:
    numero: int
    rotulo_impresso:str
    secao:str
    escopo:str
    escala:str
    moeda:str
    tipos:str
    chunks:int
    caracteres:int
    monetaria:bool=False
    marcas:str=""

@dataclass
class Arquivo:
    empresa:str
    ano:int
    trimestre:str
    doc_type:str
    caminho:str
    paginas_pdf:int=0
    segundos:float=0.0
    erro:str=""
    paginas:list=field(default_factory=list)
    chunks:int=0
    tabelas:int=0
    tabelas_monetarias:int=0
    tabelas_sem_escala:int=0
    rotulo_impresso_nulo:int=0
    escopos:Counter=field(default_factory=Counter)
    escalas:Counter=field(default_factory=Counter)

    @property
    def paginas_sem_chunk(self)->int:
        return max(0, self.paginas_pdf - len(self.paginas))

def _contar_paginas(pdf:Path)->int:
    try:
        with pdfplumber.open(pdf) as doc:
            return len(doc.pages)
    except Exception:
        return 0

def sondar_arquivo(pdf:Path, data_dir:Path, meta, chunk_size:int, chunk_overlap:int)->Arquivo:
    alvo=Arquivo(
        empresa=meta.company,
        ano=meta.year,
        trimestre=meta.quarter,
        doc_type=meta.doc_type,
        caminho=meta.source_path,
    )
    inicio=time.monotonic()
    try:
        alvo.paginas_pdf=_contar_paginas(pdf)
        chunks=extract_and_chunk(
            pdf_path=pdf,
            data_dir=data_dir,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
    except Exception as exc:
        alvo.erro=f"{type(exc).__name__}: {exc}"
        alvo.segundos=time.monotonic()-inicio
        return alvo
    alvo.segundos=time.monotonic()-inicio
    agrupado={}
    for c in chunks:
        agrupado.setdefault(c.page_number, []).append(c)

    for numero in sorted(agrupado):
        do_pagina=agrupado[numero]
        primeiro=do_pagina[0]
        escopo=primeiro.scope or NULO
        escala=primeiro.scale or NULO
        tipos=sorted({c.content_type for c in do_pagina})
        pagina=Pagina(
            numero=numero,
            rotulo_impresso=primeiro.printed_page_label or NULO,
            secao=primeiro.section_title or NULO,
            escopo=escopo,
            escala=escala,
            moeda=primeiro.currency or NULO,
            tipos="+".join(tipos),
            chunks=len(do_pagina),
            caracteres=sum(len(c.content) for c in do_pagina),
        )
        alvo.paginas.append(pagina)
        alvo.escopos[escopo]+=1
        alvo.escalas[escala]+=1
        alvo.chunks+=len(do_pagina)
        if primeiro.printed_page_label is None:
            alvo.rotulo_impresso_nulo+=1

        if "table" in tipos:
            alvo.tabelas+=1
            textos_tabela=[
                c.content.replace(c.context_header or "","")
                for c in do_pagina if c.content_type == "table"
            ]
            monetaria, marcas = marcas_monetarias(textos_tabela)
            pagina.monetaria = monetaria
            pagina.marcas="+".join(marcas[:6])
            if monetaria:
                alvo.tabelas_monetarias+=1
                if primeiro.scale is None:
                    alvo.tabelas_sem_escala+=1
    return alvo

def escolher_amostra(reconhecidos, modo:str, empresas_filtro:set)->list:
    if modo=="todos":
        return [
            (p,m) for p, m in reconhecidos
            if not empresas_filtro or m.company in empresas_filtro
        ]
    por_empresa={}
    for pdf, meta in reconhecidos:
        if empresas_filtro and meta.company not in empresas_filtro:
            continue
        if meta.doc_type=="transcricao":
            continue
        por_empresa.setdefault(meta.company, []).append((pdf, meta))

    amostra=[]
    for empresa in sorted(por_empresa):
        itens=sorted(por_empresa[empresa], key=lambda im: (im[1].year, im[1].quarter))
        escolhidos=[]
        if modo in {"antigo", "ambos"}:
            escolhidos.append(itens[0])
        if modo in {"novo", "ambos"} and itens[-1] not in escolhidos:
            escolhidos.append(itens[-1])
        amostra.extend(escolhidos)
    return amostra

def _pct(parte:int, total:int)->str:
    return "--" if total == 0 else f"{100.0 * parte / total:.1f}%"

def _topo(contador: Counter, quantos:int=4)->str:
    if not contador:
        return "-"
    return ", ".join(f"{k}={v}" for k, v in contador.most_common(quantos))

def _agrupar(arquivos:list)->dict:
    por_empresa={}
    for a in arquivos:
        por_empresa.setdefault(a.empresa, []).append(a)
    return por_empresa

def linhas_resumo(arquivos:list)->list:
    por_empresa=_agrupar(arquivos)
    linhas=[]
    cab=(f"{'empresa':<16} {'arq':>3} {'pag':>4} {'chunks':>6} {'tab':>4}"
         f"{'tab R$':>6} {'R$ s/escala':>14} escopos")
    linhas.append(cab)
    linhas.append("-" * len(cab))
            
    ordem=sorted(por_empresa, key=lambda e: (e != EMPRESA_CONTROLE, e))
    for empresa in ordem:
        grupo=por_empresa[empresa]
        paginas=sum(len(a.paginas) for a in grupo)
        chunks= sum(a.chunks for a in grupo)
        tabelas= sum(a.tabelas for a in grupo)
        monetarias= sum(a.tabelas_monetarias for a in grupo)
        sem_escala= sum(a.tabelas_sem_escala for a in grupo)
        escopos=Counter()
        for a in grupo:
            escopos.update(a.escopos)
        marca=" <-- controle" if empresa == EMPRESA_CONTROLE else ""
        linhas.append(
            f"{empresa:<16} {len(grupo)} {paginas:>4} {chunks:>6} {tabelas:>4}"
            f"{monetarias:>6} {sem_escala:>5} ({_pct(sem_escala, monetarias):>6})"
            f"{_topo(escopos)} {marca}"
        )
    return linhas

def linhas_veredito(arquivos:list)->list:
    por_empresa=_agrupar(arquivos)
    controle=por_empresa.get(EMPRESA_CONTROLE, [])
    tab_ctrl=sum(a.tabelas_monetarias for a in controle)
    sem_ctrl=sum(a.tabelas_sem_escala for a in controle)
    regua=(100.0 * sem_ctrl / tab_ctrl) if tab_ctrl else None

    linhas=["", "REGRAS DE DECISAO", "-"*78]
    if regua is None:
        linhas.append(" Sem a Copel na amostra nao ha regua de comparacao; rode com ela incluida")
    else:
        linhas.append(
            f" Regua (Copel): {regua:.1f}% das paginas com tabela de valores "
            "monetarios nao declaram escala."
        )

    for empresa in sorted (por_empresa):
        grupo=por_empresa[empresa]
        tabelas=sum(a.tabelas_monetarias for a in grupo)
        sem_escala=sum(a.tabelas_sem_escala for a in grupo)
        escopos=Counter()
        for a in grupo:
            escopos.update(a.escopos)
        paginas=sum(escopos.values())
        nulos=escopos.get(NULO, 0)
        alertas=[]
        if paginas and nulos == paginas:
            alertas.append(
                "escopo nulo em 100% das paginas"
            )
        taxa=(100.0*sem_escala / tabelas) if tabelas else 0.0
        if regua is not None and tabelas and taxa > max(regua * 2, regua+10):
            alertas.append(
                f"tabelas de valores sem escala em {taxa:.1f}%, bem acima da regua de "
                f"{regua:.1f}% - pode haver risco de ingestao "
            )
        if paginas and nulos < paginas:
            sem_alias=[
                e for e in escopos
                if e != NULO and e != "consolidado" and not e.endwith(")")
            ]
            if sem_alias:
                alertas.append(
                    "escopos sem alias em config/scopes.yaml: "
                    + ", ".join(sorted(sem_alias)[:6])
                    + " -- barato: acrecentar aliases, ou update depois"
                )
        erros=[a for a in grupo if a.erro]
        if erros:
            alertas.append(f"{len(erros)} arquivo(s) falharam na extracao")
        sem_chunk=sum(a.paginas_sem_chunk for a in grupo)
        if sem_chunk:
            alertas.append(f"{sem_chunk} pagina(s) nao produziram chunk algum")
        if alertas:
            linhas.append("")
            linhas.append(f" [ATENCAO] {empresa}")
            for a in alertas:
                linhas.append(f" - {a}")
        else:
            linhas.append(f" [ok] {empresa}")
    return linhas
def gravar_csv(arquivos:list, destino:Path)->None:
    for empresa,grupo in _agrupar(arquivos).items():
        nome="".join(ch if ch.isalnum() else "_" for ch in empresa)
        caminho=destino/f"{nome}.csv"
        with caminho.open("w", newline="", encoding="utf-8-sig") as fh:
            escritor=csv.writer(fh, delimiter=";")
            escritor.writerow([
                "arquivo", "ano", "trimestre", "doc_type", "pagina",
                "rotulo_impresso", "escopo", "escala", "moeda", "tipos",
                "monetaria", "marcas_monetarias", "chunks", "caracteres", "secao",
            ])
            for a in grupo:
                for p in a.paginas:
                    escritor.writerow([
                        a.caminho, a.ano, a.trimestre, a.doc_type, p.numero,
                        p.rotulo_impresso, p.escopo, p.escala, p.moeda, p.tipos,
                        "sim" if p.monetaria else "nao", p.marcas,
                        p.chunks, p.caracteres, p.secao,
                    ])
        logger.info("CSV gravado: %s", caminho)

def gravar_resumo(arquivos:list, descartados:list, destino:Path, modo:str)->None:
    caminho=destino/"resumo.md"
    with caminho.open("w", encoding="utf-8") as fh:
        fh.write("Sondagem de ingestao\n\n")
        fh.write(f"Amostra: `{modo}` -- {len(arquivos)} arquivo(s). ")
        fh.write("Nenhuma requisicao de embedding foi gasta.\n\n")
        fh.write("Caminhos descartados\n\n")
        if not descartados:
            fh.write("Nenhum: todos os PDFs seriam reconhecidos pela ingestao\n\n")
        else:
            for pdf, motivo in descartados:
                fh.write(f"- `{pdf.name}` -- {motivo}\n")
            fh.write("\n")
        fh.write("Resumo por empresa\n\n")
        fh.write("\n".join(linhas_resumo(arquivos)))
        fh.write("\n\n\n")
        fh.write("\n".join(linhas_veredito(arquivos)))
        fh.write("\n\n\n")
        fh.write("\nArquivos sondados\n\n")
        for a in sorted(arquivos, key=lambda x: x.caminho):
            estado=f"ERRO {a.erro}" if a.erro else (
                f"{len(a.paginas)}/{a.paginas_pdf} pag, {a.chunks} chunks"
                f"{a.tabelas} com tabela, {a.tabelas_monetarias} com valores ({a.tabelas_sem_escala} sem escala)"
            )
            fh.write(f"- `{a.caminho}` -- {estado} [{a.segundos:.1f}]\n")
    logger.info("Resumo gravado: %s", caminho)

def main()->int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    data_dir=Path(_env("DATA_DIR", "/data"))
    reconhecidos, descartados=varrer_caminhos(data_dir)

    if _env("SONDA_FASE") == "1":
        print("Sonda_fase = 1: parando depois da varredura de caminhos.")
        return 0
    if not reconhecidos:
        print("Nenhum PDF reconhecido; nada a sondar.")
        return 1
    modo=_env("SONDA_AMOSTRA", "ambos").lower()
    if modo not in {"novo", "antigo", "ambos", "todos"}:
        print(f"SONDA_AMOSTRA={modo!r} invalido. Use novo|antigo|ambos|todos.")
        return 2
    empresas={e.strip() for e in _env("SONDA_EMPRESAS").split(",") if e.strip()}
    amostra=escolher_amostra(reconhecidos, modo, empresas)
    if not amostra:
        print("A amostra ficou vazia; confira SONDA_EMPRESAS.")
        return 1

    chunk_size=_env_int("CHUNK_SIZE", 1000)
    chunk_overlap=_env_int("CHUNK_OVERLAP", 200)

    print("="*78)
    print(f"FASE 2 - sondagem de extracao ({len(amostra)} arquivo(s), amostra={modo!r})")
    print(f" chunk_size={chunk_size} chunk_overlap={chunk_overlap}")
    print("="*78)
    arquivos=[]
    for i, (pdf, meta) in enumerate(amostra, start=1):
        print(f" [{i}/{len(amostra)}] {meta.source_path}...", flush=True)
        alvo=sondar_arquivo(pdf, data_dir, meta, chunk_size, chunk_overlap)
        arquivos.append(alvo)
        if alvo.erro:
            print(f" ERRO: {alvo.erro}", flush=True)
        else:
            print(
                f"{len(alvo.paginas)}/{alvo.paginas_pdf} pag | "
                f"{alvo.chunks} chunks | tabela em {alvo.tabelas} "
                f"({alvo.tabelas_sem_escala} sem escala) | "
                f"escalas: {_topo(alvo.escalas, 3)} | {alvo.segundos:.1f}s",
                flush=True,
            )
    print()
    print("="*78)
    print("FASE 3 - relatorio")
    print("="*78)
    for linha in linhas_resumo(arquivos):
        print(linha)
    for linha in linhas_veredito(arquivos):
        print(linha)
    print()

    saida=_env("SONDA_SAIDA", "/out")
    destino=Path(saida) if saida else None
    if destino is None or not destino.is_dir():
        print(f"Diretorio de saida {saida!r} nao existe no container: relatorios nao gravados")
    else:
        destino=destino/"sondagem"
        destino.mkdir(parents=True, exist_ok=True)
        gravar_csv(arquivos, destino)
        gravar_resumo(arquivos, descartados, destino, modo)
    return 0
    
if __name__ == "__main__":
    raise SystemExit(main())