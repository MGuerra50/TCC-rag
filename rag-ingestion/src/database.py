from __future__ import annotations
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Generator, Sequence
import psycopg2
from psycopg2.extras import execute_values
from psycopg2.extensions import connection as PgConnection

logger = logging.getLogger(__name__)
EMBEDDING_DIMENSION = 768

@dataclass(frozen=True)
class ChunkRow:
    """Row ready to be inserted into document_chunks."""
    content:str
    embedding:list[float]
    company:str
    year: int
    quarter:str
    doc_type:str
    page_number:int
    source_path:str

def _dsn()->str:
    host=os.gerenv("POSTGRES_HOST","localhost")
    port=os.getenv("POSTGRES_PORT", "5432")
    dbname=os.getenv("POSTGRES_DB", "rag_db")
    user=os.getenv("POSTGRES_USER", "rag_user")
    password=os.getenv("POSTGRES_PASSWORD", "rag_password")
    return (
        f"host={host} port={port} dbname={dbname}"
        f"user={user} password={password}"
    )

@contextmanager
def get_connection()->Generator[PgConnection, None, None]:
    """Yield a PosgreSQL connection and ensure it is closed."""
    conn=psycopg2.connect(_dsn())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db()->None:
    """Create pgvector extension, document_chunks table and indexes."""
    logger.info("Initializing database schema")
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
            cur.execute(
                f"""CREATE TABLE IF NOT EXISTS document_chunks (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    content TEXT NOT NULL,
                    embedding VECTOR({EMBEDDING_DIMENSION}) NOT NULL,
                    company VARCHAR(255) NOT NULL,
                    year INT NOT NULL,
                    quarter VARCHAR(8) NOT NULL,
                    doc_type VARCHAR(64) NOT NULL,
                    page_number INT NOT NULL,
                    source_path TEXT NOT NULL
                )"""
            )
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_document_embedding ON document_chunks
                USING hnsw (embedding vector_cosine_ops)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS id_document_chunks_source_path
                ON document_chunks (source_path)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS id_document_chunks_metadata
                ON document_chunks (company, year, quarter, doc_type)
            """)
    logger.info("Database schema ready")

def delete_chunks_by_source(source_path:str)->int:
    """Remove existing chunks for a source file (idempotent re-ingestion)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM document_chunks WHERE source_path = %s",
                (source_path,),
            )
            deleted=cur.rowcount
    if deleted:
        logger.info("Deleted %s existing chunks for %s", deleted, source_path)
    return deleted

def source_already_ingested(source_path:str)->bool:
    """Return True if at least one chunk exists for the given source path."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM document_chunks WHERE source_path = %s LIMIT 1",
                (source_path,),
                )
            return cur.fetchone() is not None

def count_ingested_sources()->int:
    """Return the number of distinct source files already in the database."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(DISTINCT source_path) FROM document_chunks",
            )
        row = cur.fetchone()
        return int(row[0]) if row else 0

def count_chunks()->int:
    """Return the total number of stored chunks."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM document_chunks",
            )
            row=cur.fetchone()
        return int(row[0]) if row else 0

def _to_vector_literal(embedding: Sequence[float])->str:
    """Serialize a float vector to the pgvector text literal format."""
    return "["+",".join(str(float(value))for value in embedding)+"]"

def insert_chunks(rows:Sequence[ChunkRow])->int:
    """Bulk-insert chunk rows. Returns the number of inserted rows."""
    if not rows:
        return 0

    for row in rows:
        if len(row.embedding)!=EMBEDDING_DIMENSION:
            raise ValueError(
                f"Expected embedding dim {EMBEDDING_DIMENSION}, "
                f"got {len(row.embedding)} for source={row.source_path}"
            )

        values=[
            (
                row.content,
                _to_vector_literal(row.embedding),
                row.company,
                row.year,
                row.quarter,
                row.doc_type,
                row.page_number,
                row.source_path,
            )
            for row in rows
        ]

        sql="""
            INSERT INTO document_chunks (
                content, embedding, company, year, quarter, 
                doc_type, page_number, source-path
            ) VALUES %s    
        """

        with get_connection() as conn:
            with conn.cursor() as cur:
                execute_values(
                    cur, 
                    sql, 
                    values,
                    template="(%s, %s::vector, %s, %s, %s, %s, %s, %s)",
                    page_size=100,
                )
                inserted=len(values)

        logger.info("Inserted %s chunks", inserted)
        return inserted