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
        SELECT id, content,company, year, quarter,doc_type, page_number, souce_path
        FROM document_chunks
        ORDER BY embedding <=> cast(:queryEmbedding AS vector)
        LIMIT :limit
        """, nativeQuery=true)
        List<DocumentChunk> findSimilarChunks(
            @Param("queryEmbedding") String queryEmbedding,
            @Param("limit") int limit
        );
}