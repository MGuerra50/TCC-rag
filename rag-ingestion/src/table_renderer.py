from __future__ import annotations
import logging
import re
from dataclasses import dataclass

logger=logging.getLogger(__name__)
_NUMERIC_CELL=re.compile(r"^[\(\)\-\s]*[\d.,]+[\(\)\%\s]*$")
HEADER_SEARCH_ROWS=3

@dataclass(frozen=True)
class RenderedTable:
    header:str|None
    rows: list[str]
    column_labels:list[str]

    @property
    def is_empty(self)->bool:
        return not self.rows

def _clean_cell(cell:str|None)->str:
    if cell is None:
        return ""
    return re.sub(r"\s+", " ", str(cell)).strip()

def _looks_like_header(cells: list[str])->bool:
    filled=[c for c in cells if c]
    if len(filled)<2:
        return False
    numeric=sum(1 for c in filled if _NUMERIC_CELL.match(c))
    return numeric / len(filled)<0.5

def render_table(raw_rows: list[list[str|None]])->RenderedTable:
    cleaned: list[list[str]]=[]
    for raw in raw_rows:
        cells=[_clean_cell(c) for c in raw]
        if any(cells):
            cleaned.append(cells)
    if not cleaned:
        return RenderedTable(header=None, rows=[], column_labels=[])
    header_cells:list[str]=[]
    body=cleaned
    header_index=next(
        (
            i for i, cells in enumerate(cleaned[:HEADER_SEARCH_ROWS])
            if _looks_like_header(cells)
        ),
        None,
    )
    if header_index is not None:
        header_cells=cleaned[header_index]
        body=cleaned[:header_index]+cleaned[header_index+1:]
    header=" | ".join(header_cells) if header_cells else None
    rows=[" | ".join(cells) for cells in body]
    column_labels=_flatten_column_labels(header_cells)
    return RenderedTable(header=header, rows=rows, column_labels=column_labels)

def _flatten_column_labels(header_cells:list[str])->list[str]:
    if not header_cells:
        return []
    labels: list[str]=[]
    for index, cell in enumerate(header_cells):
        if not cell:
            continue
        if index == 0:
            labels.append(cell)
        else:
            labels.extend(cell.split())
    return labels

def chunk_table(table: RenderedTable, chunk_size:int)->list[str]:
    if table.is_empty:
        return []
    prefix=f"{table.header}\n" if table.header else ""
    prefix_len=len(prefix)
    chunks:list[str]=[]
    current:list[str]=[]
    current_len=prefix_len
    for row in table.rows:
        row_len=len(row)+1
        if current and current_len + row_len > chunk_size:
            chunks.append(prefix+"\n".join(current))
            current=[]
            current_len=prefix_len
        current.append(row)
        current_len+=row_len
    if current:
        chunks.append(prefix + "\n".join(current))
    return chunks

def subtract_table_text(page_text:str, table_texts:list[str])->str:
    if not table_texts:
        return page_text
    table_lines=set()
    for text in table_texts:
        for line in text.splitlines():
            normalized=_normalize_for_match(line)
            if normalized:
                table_lines.add(normalized)
    kept=[]
    for line in page_text.splitlines():
        normalized=_normalize_for_match(line)
        if normalized and normalized in table_lines:
            continue
        kept.append(line)
    return "\n".join(kept)

def _normalize_for_match(line:str)->str:
    return re.sub(r"[\s|]+", "", line).strip()