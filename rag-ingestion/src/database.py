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

SEP="␟"
CACHE_TABLE="embedding_cache"
LEGACY_TABLE="document_chunks"
DEFAULT_TABLE="document_chunks_v2"
TS_CONFIG="portuguese_unaccent"
ALLOWED_TABLES={LEGACY_TABLE, DEFAULT_TABLE}

def _table()->str:
    name=os.getenv("TARGET_TABLE", DEFAULT_TABLE).strip() or DEFAULT_TABLE
    if name not in ALLOWED_TABLES:
        raise ValueError(
            f"TARGET_TABLE={name} não é permitida. Use uma destas {sorted(ALLOWED_TABLES)}"
        )
    return name

@dataclass(frozen=True)
class ChunkRow:
    content:str
    embedding:list[float]
    company:str
    year: int
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
    content_header:str|None=None
    chunk_index:int=0

def _dsn()->str:
    host=os.getenv("POSTGRES_HOST","localhost")
    port=os.getenv("POSTGRES_PORT", "5432")
    dbname=os.getenv("POSTGRES_DB", "rag_db")
    user=os.getenv("POSTGRES_USER", "rag_user")
    password=os.getenv("POSTGRES_PASSWORD", "rag_password")
    return (
        f"host={host} port={port} dbname={dbname} "
        f"user={user} password={password}"
    )

@contextmanager
def get_connection()->Generator[PgConnection, None, None]:
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
    table=_table()
    if table==LEGACY_TABLE and  os.getenv("ALLOW_LEGACY_DDL","").strip().lower() not in {
        "1",
        "true", 
        "yes", 
        "y",
        "on",
    }:

        raise RuntimeError(
            f"Ação não pode ser executada na tabela antiga '{LEGACY_TABLE}'."
        )

    logger.info("Inicializando o schema do banco de dados para a tabela'%s'", table)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
            cur.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
            cur.execute(
                """DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_ts_config WHERE cfgname = '{TS_CONFIG}'
                    ) THEN 
                        CREATE TEXT SEARCH CONFIGURATION {TS_CONFIG} (COPY = portuguese);
                        ALTER TEXT SEARCH CONFIGURATION {TS_CONFIG}
                        ALTER MAPPING FOR hword, hword_part, word
                        WITH unaccent, portuguese_stem;
                    END IF;
                END
                $$;"""
            )
            cur.execute(
                f"""CREATE TABLE IF NOT EXISTS {table} (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    content TEXT NOT NULL,
                    embedding VECTOR({EMBEDDING_DIMENSION}) NOT NULL,
                    company VARCHAR(255) NOT NULL,
                    year INT NOT NULL,
                    quarter VARCHAR(8) NOT NULL,
                    doc_type VARCHAR(64) NOT NULL,
                    page_number INT NOT NULL,
                    source_path TEXT NOT NULL,
                    section_title TEXT,
                    scope VARCHAR(64),
                    scale VARCHAR(16),
                    currency VARCHAR(8),
                    scale_source VARCHAR(16),
                    printed_page_label VARCHAR(16),
                    content_type VARCHAR(16) NOT NULL DEFAULT 'text',
                    content_header TEXT,
                    chunk_index INT NOT NULL DEFAULT 0,
                    content_tsv tsvector GENERATED ALWAYS AS (
                        to_tsvector('{TS_CONFIG}', content)
                    ) STORED
                )"""
            )
            cur.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = %s AND column_name = 'scale_source'",
                (table,),
            )
            coluna_ja_existe=cur.fetchone() is not None
            cur.execute(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS scale_source VARCHAR(16)"
            )
            if not coluna_ja_existe:
                cur.execute(
                    "UPDATE {table} SET scale_source='pagina' "
                    "WHERE scale IS NOT NULL AND scale_source IS NULL"
                )
                logger.info(
                    "Migracao (unica): %s linha(s) anteriores a coluna marcadas "
                    "com scale_source='pagina'",
                    cur.rowcount
                )
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_{table}_embedding ON {table}
                USING hnsw (embedding vector_cosine_ops)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_{table}_source_path
                ON {table} (source_path)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_{table}_metadata
                ON {table} (company, year, quarter, doc_type)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_{table}_scope
                ON {table} (company, scope)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_{table}_tsv
                ON {table} USING gin (content_tsv)
            """)
            cur.execute(
                f"""CREATE TABLE IF NOT EXISTS {CACHE_TABLE} (
                    content_hash CHAR(64) PRIMARY KEY,
                    embedding VECTOR({EMBEDDING_DIMENSION}) NOT NULL,
                    model VARCHAR(128) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )"""
            )
    logger.info("Schema do banco pronto para a tabela '%s'", table)

def delete_chunks_by_source(source_path:str)->int:
    table=_table()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {table} WHERE source_path = %s",
                (source_path,),
            )
            deleted=cur.rowcount
    if deleted:
        logger.info(" %s trechos existentes removidos de %s", deleted, source_path)
    return deleted

def source_already_ingested(source_path:str)->bool:
    table=_table()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT 1 FROM {table} WHERE source_path = %s LIMIT 1",
                (source_path,),
                )
            return cur.fetchone() is not None

def count_ingested_sources()->int:
    table=_table()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(DISTINCT source_path) FROM {table}",
            )
            row = cur.fetchone()
        return int(row[0]) if row else 0

def count_chunks()->int:
    table=_table()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) FROM {table}",
            )
            row=cur.fetchone()
        return int(row[0]) if row else 0

def _to_vector_literal(embedding: Sequence[float])->str:
    return "["+",".join(str(float(value))for value in embedding)+"]"

def insert_chunks(rows:Sequence[ChunkRow])->int:
    if not rows:
        return 0

    for row in rows:
        if len(row.embedding)!=EMBEDDING_DIMENSION:
            raise ValueError(
                f"Dimensão de embeddings esperada {EMBEDDING_DIMENSION}, "
                f"recebida {len(row.embedding)} para source={row.source_path}"
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
                row.section_title,
                row.scope,
                row.scale,
                row.currency,
                row.scale_source,
                row.printed_page_label,
                row.content_type,
                row.content_header,
                row.chunk_index
            )
            for row in rows
        ]

        table=_table()
        sql="""
            INSERT INTO {table} (
                content, embedding, company, year, quarter, 
                doc_type, page_number, source_path,
                section_title, scope, scale, currency,
                scale_source, printed_page_label, content_type,
                context_header, chunk_index
            ) VALUES %s    
        """

        with get_connection() as conn:
            with conn.cursor() as cur:
                execute_values(
                    cur, 
                    sql, 
                    values,
                    template=(
                        "(%s, %s::vector, %s, %s, %s, %s, %s, %s, "
                        "%s, %s, %s, %s, %s, %s, %s, %s, %s)"
                    ),
                    page_size=100,
                )
                inserted=len(values)

        logger.info(" %s chunks inseridos em %s", inserted, table)
        return inserted

def embedding_cache_key(text: str, model: str, dimension: int = EMBEDDING_DIMENSION,
                        task_type: str = "retrieval_document")->str:
    import hashlib
    material = SEP.join([model, str(dimension), task_type, text])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()

def _parse_vector_literal(raw: str)->list[float]:
    return [float(x) for x in raw.lstrip("[").rstrip("]").split(",") if x]

def get_cached_embeddings(keys: Sequence[str])->dict[str, list[float]]:
    if not keys:
        return {}
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT content_hash, embedding::text FROM {CACHE_TABLE} "
                f"WHERE  content_hash = ANY(%s)",
                (list(keys),),
            )
            return {row[0]: _parse_vector_literal(row[1]) for row in cur.fetchall()}

def put_cached_embeddings(items: Sequence[tuple])->int:
    if not items:
        return 0
    values=[(h, _to_vector_literal(vec), model) for h, vec, model in items]
    with get_connection() as conn:
        with conn.cursor() as cur:
            execute_values(
                cur,
                f"INSERT INTO {CACHE_TABLE} (content_hash, embedding, model) VALUES %s "
                f"ON CONFLICT (content_hash) DO NOTHING",
                values,
                template="(%s, %s::vector, %s)",
                page_size=100,
            )
    return len(values)

def count_cached() -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {CACHE_TABLE}")
            row = cur.fetchone()
            return int(row[0]) if row else 0
        