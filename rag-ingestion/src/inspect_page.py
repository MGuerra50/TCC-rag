from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


from src.pdf_processor import extract_and_chunk

def main(argv: list[str])->int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(levelname)-8s | %(name)s | %(message)s",
        stream=sys.stderr,
    )

    if not argv:
        print(__doc__)
        return 2

    pdf_path=Path(argv[0]).resolve()
    if not pdf_path.exists():
        print(f"PDF não encontrado: {pdf_path}", file=sys.stderr)
        return 1

    page_filter=int(argv[1]) if len(argv) > 1 else None

    data_dir=Path(os.getenv("DATA_DIR", "")) if os.getenv("DATA_DIR") else None
    if data_dir is None or not data_dir.exists():
        data_dir=pdf_path.parent.parent.parent.parent
        if not data_dir.exists():
            data_dir=pdf_path.parent.parent.parent

    chunk_size=int(os.getenv("CHUNK_SIZE", "1000"))
    chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "200"))
    chunks=extract_and_chunk(
        pdf_path=pdf_path,
        data_dir=data_dir,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    selected=[c for c in chunks if page_filter is None or c.page_number == page_filter]
    if not selected:
        print(f"Nenhum chunk gerado para essa página {page_filter} de {pdf_path}")
        return 1

    print(f"data_dir={data_dir}")
    print(f"{len(selected)} chunk(s)\n")
    for i, chunk in enumerate(selected, start=1):
        print("="*78)
        print(
            f"chunk {i} | pagina={chunk.page_number} "
            f"(impressa={chunk.printed_page_label}) index={chunk.chunk_index} "
            f"tipo={chunk.content_type}"
        )
        print(
            f" escopo={chunk.scope!r} escala={chunk.scale!r}"
            f"moeda={chunk.currency!r}"
        )
        print(f" seção={chunk.section_title!r}")
        print(f" caracteres={len(chunk.content)}")
        print("="*78)
        print(chunk.content)
        print()

    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))