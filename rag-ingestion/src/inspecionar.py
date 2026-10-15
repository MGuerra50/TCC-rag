from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
import pdfplumber

from src.page_context import (
    SCALE_SCAN_EXTRA_LINES,
    detect_scale,
)
from src.pdf_processor import (
    DEFAULT_FOOTER_ZONE_RATIO,
    DEFAULT_HEADER_ZONE_RATIO,
    _extract_page_zones,
    discover_pdfs,
    parse_metadata,
)

def _env(nome:str, padrao:str="")->str:
    return (os.getenv(nome) or padrao).strip()

def _mostrar(rotulo:str, texto: str)-> None:
    print(f"   ---{rotulo}---   ")
    if not texto.strip():
        print("         [ Vazio ]")
        return
    for linha in texto.splitlines():
        print(f" | {linha}")

def main()-> int:
    logging.basicConfig(level=logging.ERROR, stream=sys.stdout)
    alvo=_env("INSPECT_ARQUIVO")
    if not alvo:
        print("Defina INSPECT_ARQUIVO com parte do caminho do PDF.")
        return 2

    data_dir = Path(_env("DATA_DIR", "/data"))
    quantas=int(_env("INSPECT_QUANTAS", "3"))
    largura=int(_env("INSPECT_LINHAS", "18"))
    paginas_perdidas={
        int(p) for p in _env("INSPECT_PAGINAS").replace(";", ",").split(",") if p.strip()
    }

    candidatos = [
        p for p in discover_pdfs(data_dir)
        if alvo.lower() in p.resolve().relative_to(data_dir.resolve()).as_posix().lower()
    ]
    if not candidatos:
        print(f"Nenhum PDF casa com {alvo!r}; usando o primeiro:")
        for c in candidatos:
            print(f"    {c.relative_to(data_dir)}")

    pdf_path=candidatos[0]
    meta=parse_metadata(pdf_path, data_dir)
    print("="*78)
    print(f"{meta.source_path if meta else pdf_path.name}")
    print("="*78)

    mostradas=0
    with pdfplumber.open(pdf_path) as pdf:
        for indice, page in enumerate(pdf.pages, start=1):
            if paginas_perdidas and indice not in paginas_perdidas:
                continue
            header, body, _ = _extract_page_zones(
                page, DEFAULT_HEADER_ZONE_RATIO, DEFAULT_FOOTER_ZONE_RATIO
            )
            body_head="\n".join(body.splitlines()[:SCALE_SCAN_EXTRA_LINES])
            escala, moeda = detect_scale(header, body_head)
            tem_tabela=bool(page.find_tables())

            if not paginas_perdidas:
                if escala is not None or not tem_tabela:
                    continue

            print()
            print(f" PAGINA {indice} tabela={tem_tabela} "
                  f" escala_detectada={escala} moeda={moeda} ")
            _mostrar(f"zona de cabecalho (0 a {DEFAULT_HEADER_ZONE_RATIO:.0%} da altura)", header)
            _mostrar(f"primeiras {SCALE_SCAN_EXTRA_LINES} linhas do corpo (tambem varridas)", body_head)
            resto="\n".join(body.splitlines()[SCALE_SCAN_EXTRA_LINES:largura])
            _mostrar(f"corpo, linhas {SCALE_SCAN_EXTRA_LINES + 1} a {largura} (NAO varridas hoje)", resto)

            mostradas+=1
            if not paginas_perdidas and mostradas >= quantas:
                break
            
    if mostradas == 0:
        print("\n Nenhuma pagina se encaixa no criterio")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
    