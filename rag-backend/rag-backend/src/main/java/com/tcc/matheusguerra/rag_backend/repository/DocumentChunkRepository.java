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
        SELECT id, content,company, year, quarter,doc_type, page_number, source_path, embedding,
                (embedding <=> cast(:queryEmbedding AS vector)) AS distance
        FROM document_chunks
        WHERE (embedding <=> cast(:queryEmbedding AS vector)) < :maxDistance
        ORDER BY distance
        LIMIT :limit
        """, nativeQuery=true)
        List<DocumentChunk> findSimilarChunks(
            @Param("queryEmbedding") String queryEmbedding,
            @Param("limit") int limit,
            @Param("maxDistance") double maxDistance
        );

    @Query (value="SELECT DISTINCT company FROM  document_chunks ORDER BY company", nativeQuery=true)
    List<String> findDistinctCompanies();
}