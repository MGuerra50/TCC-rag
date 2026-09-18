from __future__ import annotations
import logging
import re
from dataclasses import dataclass
from pathlib import Path
import pdfplumber
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger=logging.getLogger(__name__)

QUARTER_FROM_FOLDER=re.compile(r"^(?:T([1-4])|([1-4])T)$", re.IGNORECASE)
QUARTER_FROM_FILENAME=re.compile(r"(?:^|[^\d])([1-4])T\d{2}(?:[^\d]|$)", re.IGNORECASE)
YEAR_FOLDER=re.compile(r"^\d{4}$")

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

def normalize_quarter(raw:str)->str|None:
    match=QUARTER_FROM_FOLDER.match(raw.strip())
    if not match:
        return None
    digit=match.group(1) or match.group(2)
    return f"{digit}T"

def infer_doc_type(filename:str)->str:
    name=filename.lower()
    if "transcri" in name:
        return "transcricao"
    if "release" in name or "press" in name:
        return "release"
    logger.warning("Could not infer doc_type from filename '%s'; using 'outro", filename)
    return "outro"

def parse_metadata(pdf_path:Path, data_dir:Path)->DocumentMetadata|None:
    try:
        relative=pdf_path.resolve().relative_to(data_dir.resolve())
    except ValueError:
        logger.warning("PDF outside data dir, skipping: %s", pdf_path)
        return None

    parts=relative.parts
    if len(parts)<3:
        logger.warning("Unexpected path depth for %s (parts=%s)",pdf_path, parts)
        return None

    company=parts[0]
    year_raw=parts[1]
    if not YEAR_FOLDER.match(year_raw):
        logger.warning("Invalid year folder '%s' in %s", year_raw, pdf_path)
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
                "Quarter folder missing for %s; inferred '%s' from filename",
                source_path,
                quarter,
            )
        else:
            logger.warning("Could not determine quarter for %s; skipping", source_path)
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
        logger.error("Data directory does not exist: %s", data_dir)
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
            "Ignoring %s .docx file(s); only PDF is supported in this pipeline",
            docx_count,
        )

    logger.info("Discovered %s PDF file(s) under %s", len(pdfs), data_dir)
    return pdfs

def _build_splitter(chunk_size:int, chunk_overlap:int)->RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

def extract_and_chunk(
        pdf_path:Path,
        data_dir:Path,
        chunk_size:int=1000,
        chunk_overlap:int=200,
)->list[DocumentChunk]:
    metadata=parse_metadata(pdf_path, data_dir)
    if metadata is None:
        return []

    splitter=_build_splitter(chunk_size, chunk_overlap)
    chunks:list[DocumentChunk]=[]

    try:
        with pdfplumber.open(pdf_path) as pdf:
            total_pages=len(pdf.pages)
            logger.info(
                "Extracting %s (%s pages) company=%s year=%s quarter=%s type=%s",
                metadata.source_path,
                total_pages,
                metadata.company,
                metadata.year,
                metadata.quarter,
                metadata.doc_type,
            )
            for page_index, page in enumerate(pdf.pages, start=1):
                text=(page.extract_text() or "").strip()
                if not text:
                    logger.debug(
                        "Empty text on page %s of %s",
                        page_index,
                        metadata.source_path,
                    )
                    continue

                page_chunks=splitter.split_text(text)
                logger.info(
                    "Page %s/%s of %s -> %s chunk(s)",
                    page_index,
                    total_pages,
                    metadata.source_path,
                    len(page_chunks),
                )
                for chunk_text in page_chunks:
                    chunks.append(
                        DocumentChunk(
                            content=chunk_text,
                            company=metadata.company,
                            year=metadata.year,
                            quarter=metadata.quarter,
                            doc_type=metadata.doc_type,
                            page_number=page_index,
                            source_path=metadata.source_path,
                        )
                    )
    except Exception:
        logger.exception("Failed to process PDF %s", pdf_path)
        return []

    logger.info("Produced %s chunks from %s", len(chunks), metadata.source_path)
    return chunks