from __future__ import annotations
import logging
import re
import os
from dataclasses import dataclass
from pathlib import Path
import pdfplumber
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.page_context import(
    DEFAULT_FOOTER_ZONE_RATIO,
    DEFAULT_HEADER_ZONE_RATIO,
    PageContext,
    build_context_preamble,
    build_footer_blacklist,
    detect_document_scale,
    detect_page_scale,
    detect_section_and_scope,
    marcas_monetarias,
    extract_printed_page_label,
    load_scope_rules,
    remove_blacklisted_lines,
)
from src.table_renderer import chunk_table, render_table, subtract_table_text

logger=logging.getLogger(__name__)

QUARTER_FROM_FOLDER=re.compile(r"^(?:T([1-4])|([1-4])T)$", re.IGNORECASE)
QUARTER_FROM_FILENAME=re.compile(r"(?:^|[^\d])([1-4])T\d{2}(?:[^\d]|$)", re.IGNORECASE)
YEAR_FOLDER=re.compile(r"^\d{4}$")
MIN_CHUNK_BODY_CHARS=40
SCOPE_CONFIG_PATH=Path(
    os.getenv("SCOPE_CONFIG", str(Path(__file__).resolve().parent.parent / "config" / "scopes.yaml"))
)

@dataclass(frozen=True)
class DocumentMetadata:
    company: str
    year:int
    quarter:str
    doc_type:str
    source_path:str

@dataclass(frozen=True)
class DocumentChunk:
    content:str
    company: str
    year:int
    quarter:str
    doc_type:str
    page_number:int
    source_path:str
    section_title:str|None=None
    scope:str|None=None
    scale:str|None=None
    currency:str|None=None
    scale_source:str|None=None
    printed_page_label:str|None=None
    content_type:str="text"
    context_header:str|None=None
    chunk_index:int=0

def normalize_quarter(raw:str)->str|None:
    match=QUARTER_FROM_FOLDER.match(raw.strip())
    if not match:
        return None
    digit=match.group(1) or match.group(2)
    return f"{digit}T"

_RELEASE_HINTS=(
    "release", "press", "resultado", "demonstra", "informe"
)

def infer_doc_type(filename:str)->str:
    name=filename.lower()
    if "transcri" in name:
        return "transcricao"
    if any(hint in name for hint in _RELEASE_HINTS):
        return "release"
    if re.match(r"^elp\d", name):
        return "release"
    logger.warning("Não foi possível inferir os docType pelo nome do arquivo '%s'; utilizando 'outro'", filename)
    return "outro"


def parse_metadata(pdf_path:Path, data_dir:Path)->DocumentMetadata|None:
    try:
        relative=pdf_path.resolve().relative_to(data_dir.resolve())
    except ValueError:
        logger.warning("PDF fora do diretório de dados, pulando: %s", pdf_path)
        return None

    parts=relative.parts
    if len(parts)<3:
        logger.warning("Profundidade da pasta inesperada para %s (partes=%s)",pdf_path, parts)
        return None

    company=parts[0]
    year_raw=parts[1]
    if not YEAR_FOLDER.match(year_raw):
        logger.warning("Pasta de ano inválida '%s' em %s", year_raw, pdf_path)
        return None
    year = int(year_raw)

    filename=parts[-1]
    source_path=relative.as_posix()

    quarter:str|None=None
    if len(parts)>=4:
        quarter=normalize_quarter(parts[2])

    if quarter is None:
        filename_match=QUARTER_FROM_FILENAME.search(filename)
        if filename_match:
            quarter=f"{filename_match.group(1)}T"
            logger.warning(
                "Pasta de trimestre ausente para %s; inferido pelo nome do arquivo '%s'",
                source_path,
                quarter,
            )
        else:
            logger.warning("Não foi possível determinar o trimestre de %s; pulando", source_path)
            return None

    doc_type=infer_doc_type(filename)
    return DocumentMetadata(
        company=company,
        year=year,
        quarter=quarter,
        doc_type=doc_type,
        source_path=source_path,
    )

def discover_pdfs(data_dir:Path)->list[Path]:
    if not data_dir.exists():
        logger.error("Diretório não existe: %s", data_dir)
        return []

    pdfs=sorted(
        {
            p.resolve()
            for p in data_dir.rglob("*")
            if p.is_file() and p.suffix.lower()==".pdf"
        }
    )

    docx_count=sum(
        1 for p in data_dir.rglob("*") if p.is_file() and p.suffix.lower() == ".docx"
    )
    if docx_count:
        logger.warning(
            "Ignorando arquivos %s .docx; São aceitos somente arquivos PDF.",
            docx_count,
        )

    logger.info(" %s Arquivos PDF encontrados em %s", len(pdfs), data_dir)
    return pdfs

def _build_splitter(chunk_size:int, chunk_overlap:int)->RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

def _env_float(name:str, default:float)->float:
    raw=os.getenv(name)
    if raw is None or raw.strip()=="":
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Valor decimal inválido para  %s='%s'; usando %s", name, raw, default)
        return default

def _crop_text(page, top_ratio: float, bottom_ratio:float)->str:
    try:
        height=page.height
        bbox=(0, height*top_ratio, page.width, height*bottom_ratio)
        return (page.crop(bbox).extract_text() or "").strip()
    except Exception:
        logger.debug("Falha ao recortar página; usando faixa vazia", exc_info=True)
        return ""

def _extract_page_zones(page, header_ratio:float, footer_ratio:float)->tuple[str, str, str]:
    header=_crop_text(page, 0.0, header_ratio)
    body=_crop_text(page, header_ratio, footer_ratio)
    footer=_crop_text(page, footer_ratio, 1.0)
    if not body:
        body=(page.extract_text() or "").strip()
    return header, body, footer

def extract_and_chunk(
        pdf_path:Path,
        data_dir:Path,
        chunk_size:int=1000,
        chunk_overlap:int=200,
)->list[DocumentChunk]:
    metadata=parse_metadata(pdf_path, data_dir)
    if metadata is None:
        return []

    header_ratio=_env_float("HEADER_ZONE_RATIO", DEFAULT_HEADER_ZONE_RATIO)
    footer_ratio=_env_float("FOOTER_ZONE_RATIO", DEFAULT_FOOTER_ZONE_RATIO)
    scope_rules=load_scope_rules(SCOPE_CONFIG_PATH, metadata.company)
    splitter=_build_splitter(chunk_size, chunk_overlap)
    chunks:list[DocumentChunk]=[]

    try:
        with pdfplumber.open(pdf_path) as pdf:
            total_pages=len(pdf.pages)
            logger.info(
                "Extraindo %s (%s paginas) empresa=%s ano=%s trimestre=%s tipo=%s",
                metadata.source_path,
                total_pages,
                metadata.company,
                metadata.year,
                metadata.quarter,
                metadata.doc_type,
            )
            pages:list[tuple[int, str, str, str]]=[]
            footers:list[str]=[]
            for page_index, page in enumerate(pdf.pages, start=1):
                header, body, footer=_extract_page_zones(page, header_ratio, footer_ratio)
                pages.append((page_index, header, body, footer))
                footers.append(footer)
            blacklist=build_footer_blacklist(footers, total_pages)
            if os.getenv("DOC_SCALE", "").strip().lower()=="off":
                doc_scale, doc_currency=None, None
            else:
                doc_scale, doc_currency=detect_document_scale(
                    [f"{h}\n{b}" for _, h, b, _ in pages]
                )
            if doc_scale:
                logger.info(
                    "%s declara escala global '%s' (%s); paginas monetarias sem "
                    "escala propria vao herda-la",
                    metadata.source_path, doc_scale, doc_currency,
                )
            last_scope:str|None=None
            for page_index, header_text, body_text, footer_text in pages:
                page=pdf.pages[page_index-1]
                body_text=remove_blacklisted_lines(body_text, blacklist)
                if not body_text.strip():
                    logger.debug(
                        "Texto vazio na página %s de %s",
                        page_index,
                        metadata.source_path,
                    )
                    continue
                section_title, scope, starts_new_section=detect_section_and_scope(
                    header_text, scope_rules
                )
                if scope is not None:
                    last_scope=scope
                elif starts_new_section:
                    last_scope=None
                else:
                    scope=last_scope
                scale, currency = detect_page_scale(header_text, body_text)
                scale_source="pagina" if scale is not None else None
                printed_label=extract_printed_page_label(footer_text)
                table_chunks, column_labels, table_texts=_extract_tables(
                    page, chunk_size
                )
                if scale is None and doc_scale is not None:
                    monetaria, _ = marcas_monetarias(table_texts)
                    if monetaria:
                        scale, currency = doc_scale, doc_currency
                        scale_source="documento"
                context=PageContext(
                    section_title=section_title,
                    scope=scope,
                    scale=scale,
                    currency=currency,
                    printed_page_label=printed_label,
                    column_labels=column_labels,
                    scale_source=scale_source,
                )
                preamble=build_context_preamble(
                    company=metadata.company,
                    year=metadata.year,
                    quarter=metadata.quarter,
                    doc_type=metadata.doc_type,
                    page_number=page_index,
                    context=context,
                )

                narrative=subtract_table_text(body_text, table_texts).strip()
                text_chunks=splitter.split_text(narrative) if narrative else []
                page_pieces=[
                    (c, kind)
                    for c, kind in (
                        [(c, "table") for c in table_chunks]
                        +[(c, "text") for c in text_chunks]
                    )
                    if len(c.strip()) >= MIN_CHUNK_BODY_CHARS
                ]
                logger.info(
                    "Página %s/%s de %s -> %s chunk(s) [%s tabela, %s texto] escopo=%s escala=%s",
                    page_index,
                    total_pages,
                    metadata.source_path,
                    len(page_pieces),
                    len(table_chunks),
                    len(text_chunks),
                    scope,
                    scale,
                )

                for chunk_index, (chunk_text, content_type) in enumerate(page_pieces):
                    chunks.append(
                        DocumentChunk(
                            content=f"{preamble}\n{chunk_text}",
                            company=metadata.company,
                            year=metadata.year,
                            quarter=metadata.quarter,
                            doc_type=metadata.doc_type,
                            page_number=page_index,
                            source_path=metadata.source_path,
                            section_title=section_title,
                            scope=scope,
                            scale=scale,
                            currency=currency,
                            scale_source=scale_source,
                            printed_page_label=printed_label,
                            content_type=content_type,
                            context_header=preamble,
                            chunk_index=chunk_index,
                        )
                    )
    except Exception:
        logger.exception("Falha ao processar PDF %s", pdf_path)
        return []

    logger.info(" %s chunks gerados a partir de %s", len(chunks), metadata.source_path)
    return chunks

def _extract_tables(page, chunk_size:int)->tuple[list[str], list[str], list[str]]:
    table_chunks:list[str]=[]
    table_texts:list[str]=[]
    column_labels:list[str]=[]
    try:
        raw_tables=page.extract_tables() or []
    except Exception:
        logger.debug("Falha na extração das tabelas da página ", exc_info=True)
        return [],[],[]

    for raw_table in raw_tables:
        rendered=render_table(raw_table)
        if rendered.is_empty:
            continue
        if len(rendered.column_labels)> len(column_labels):
            column_labels=rendered.column_labels
        pieces=chunk_table(rendered, chunk_size)
        table_chunks.extend(pieces)
        if rendered.header:
            table_texts.append(rendered.header)
        table_texts.extend(rendered.rows)

    return table_chunks, column_labels, table_texts