package com.tcc.matheusguerra.rag_backend.repository;
import java.util.List;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import com.tcc.matheusguerra.rag_backend.model.DocumentChunkV2;

@Repository 
public interface DocumentChunkV2Repository extends JpaRepository<DocumentChunkV2,UUID>{
    @Query(value="""
            WITH dense AS (
                SELECT id,
                    (embedding<=>CAST(:queryEmbedding AS vector)) AS distance,
                    ROW_NUMBER() OVER (
                        ORDER BY embedding <=> CAST(:queryEmbedding AS vector)
                    ) AS rank
                FROM document_chunks_v2
                WHERE (CAST(:company AS text) IS NULL OR company ILIKE CAST(:company AS text))
                    AND (CAST(:year AS int) IS NULL OR year = CAST(:year AS int))
                    AND (CAST(:quarter AS text) IS NULL OR quarter = CAST(:quarter AS text))
                    AND (CAST(:scope AS text) IS NULL OR scope ILIKE CAST(:scope AS text))
                ORDER BY embedding <=> CAST(:queryEmbedding AS vector)
                LIMIT :poolSize
            ),
            lexical AS (
                SELECT id,
                        ROW_NUMBER() OVER (
                            ORDER BY ts_rank(
                                content_tsv,
                                plainto_tsquery('portuguese_unaccent', CAST(:question AS text))
                            ) DESC
                        ) AS rank
                FROM document_chunks_v2
                WHERE content_tsv @@ plainto_tsquery('portuguese_unaccent', CAST(:question AS text))
                    AND (CAST(:company AS text) IS NULL OR company ILIKE CAST(:company AS text))
                    AND (CAST(:year AS int) IS NULL OR year = CAST(:year AS int))
                    AND (CAST(:quarter AS text) IS NULL OR quarter = CAST(:quarter AS text))
                    AND (CAST(:scope AS text) IS NULL OR scope ILIKE CAST(:scope AS text))
                ORDER BY ts_rank(
                    content_tsv,
                    plainto_tsquery('portuguese_unaccent', CAST(:question AS text))
                ) DESC
                LIMIT :poolSize
            ),
            fused AS (
                SELECT COALESCE(d.id, l.id) AS id,
                    d.distance AS distance,
                    COALESCE(1.0 / (60 + d.rank), 0.0) 
                        + COALESCE(1.0 / (60 + l.rank), 0.0) AS score
                FROM dense d
                FULL OUTER JOIN lexical l ON d.id = l.id
            )
            SELECT c.id AS id,
                c.content AS content,
                c.company AS company,
                c.year AS year,
                c.quarter AS quarter,
                c.doc_type AS docType,
                c.page_number AS pageNumber,
                c.source_path AS sourcePath,
                c.section_title AS sectionTitle,
                c.scope AS scope,
                c.scale AS scale,
                c.scale_source AS scaleSource,
                c.currency AS currency,
                c.printed_page_label AS printedPageLabel,
                c.content_type AS contentType,
                f.distance AS distance,
                f.score AS score
            FROM fused f
            JOIN document_chunks_v2 c ON c.id = f.id
            WHERE f.distance IS NULL OR f.distance < :maxDistance
            ORDER BY f.score DESC
            LIMIT :limit
            """, nativeQuery=true)
    List<ChunkWithScore> findSimilarChunksFiltered(
            @Param("queryEmbedding") String queryEmbedding,
            @Param("question") String question,
            @Param("company") String company,
            @Param("year") Integer year,
            @Param("quarter") String quarter,
            @Param("scope") String scope,
            @Param("poolSize") int poolSize,
            @Param("limit") int limit,
            @Param("maxDistance") double maxDistance 
    );

    @Query(value= "SELECT DISTINCT company FROM document_chunks_v2 ORDER BY company", nativeQuery = true)
    List<String> findDistinctCompanies();
    
    @Query(value = """
                SELECT year, quarter
                FROM document_chunks_v2
                WHERE company ILIKE :company
                ORDER BY year DESC, LEFT(quarter, 1) DESC
                LIMIT 1
            """, nativeQuery = true)
    List<Object[]> findLatestPeriod(@Param("company") String company);
}
