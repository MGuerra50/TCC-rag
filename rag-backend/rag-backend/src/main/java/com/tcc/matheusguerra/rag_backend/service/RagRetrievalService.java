package com.tcc.matheusguerra.rag_backend.service;

import java.util.List;
import java.util.stream.Collectors;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.embedding.EmbeddingModel;
import org.springframework.stereotype.Service;
import com.tcc.matheusguerra.rag_backend.dto.SearchResponse;
import com.tcc.matheusguerra.rag_backend.model.DocumentChunk;
import com.tcc.matheusguerra.rag_backend.repository.DocumentChunkRepository;

@Service
public class RagRetrievalService {
    private static final Logger log = LoggerFactory.getLogger(RagRetrievalService.class);
    private final DocumentChunkRepository repository;
    private final EmbeddingModel embeddingModel;

    public RagRetrievalService(DocumentChunkRepository repository, EmbeddingModel embeddingModel) {
        this.repository = repository;
        this.embeddingModel = embeddingModel;
    }

    public SearchResponse search(String question, int limit) {
        log.info("Iniciando busca semântica para \"{}\" limit={}", question, limit);
        float[] vector = embeddingModel.embed(question);
        log.debug("Embedding gerado com {} dimensões", vector.length);
        String pgVectorString = formatVectorForPgVector(vector);
        List<DocumentChunk> chunks = repository.findSimilarChunks(pgVectorString, limit);

        log.info("Busca retornou {} chunks relevantes", chunks.size());
        return buildResponse(question, chunks);
    }

    private String formatVectorForPgVector(float[] vector) {
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < vector.length; i++) {
            if (i > 0) {
                sb.append(",");
            }
            sb.append(vector[i]);

        }
        sb.append("]");
        return sb.toString();
    }

    private SearchResponse buildResponse(String question, List<DocumentChunk> chunks) {
        List<SearchResponse.ChunkResult> results = chunks.stream()
                .map(chunk -> new SearchResponse.ChunkResult(
                        chunk.getId(),
                        chunk.getContent(),
                        chunk.getCompany(),
                        chunk.getYear(),
                        chunk.getQuarter(),
                        chunk.getDocType(),
                        chunk.getPageNumber(),
                        chunk.getSourcePath()))
                .collect(Collectors.toList());
        return new SearchResponse(question, results.size(), results);
    }
}