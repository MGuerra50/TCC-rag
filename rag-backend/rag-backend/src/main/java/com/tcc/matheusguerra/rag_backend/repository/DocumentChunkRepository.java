package com.tcc.matheusguerra.rag_backend.repository;
import java.util.List;
import java.util.UUID;
import org.springframework.stereotype.Repository;
import com.tcc.matheusguerra.rag_backend.model.DocumentChunk;
import org.springframework.data.repository.query.Param;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.jpa.repository.JpaRepository;

@Repository
public interface DocumentChunkRepository extends JpaRepository<DocumentChunk, UUID> {
    @Query(value="""
        SELECT id AS id, 
        content AS content,
        company AS company, 
        year AS year, 
        quarter AS quarter,
        doc_type AS docType, 
        page_number AS pageNumber, 
        source_path AS sourcePath,
        CAST(NULL AS text) AS sectionTitle,
        CAST(NULL AS text) AS scope,
        CAST(NULL AS text) AS scale,
        CAST(NULL AS text) AS scaleSource,
        CAST(NULL AS text) AS currency,
        CAST(NULL AS text) AS printedPageLabel,
        CAST(NULL AS text) AS contentType,
        (embedding <=> cast(:queryEmbedding AS vector)) AS distance,
        CAST(NULL AS double precision) AS score
        FROM document_chunks
        WHERE (embedding <=> cast(:queryEmbedding AS vector)) < :maxDistance
        ORDER BY distance
        LIMIT :limit
        """, nativeQuery=true)
        List<ChunkWithScore> findSimilarChunks(
            @Param("queryEmbedding") String queryEmbedding,
            @Param("limit") int limit,
            @Param("maxDistance") double maxDistance
        );

    @Query (value="SELECT DISTINCT company FROM  document_chunks ORDER BY company", nativeQuery=true)
    List<String> findDistinctCompanies();
}