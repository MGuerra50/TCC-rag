package com.tcc.matheusguerra.rag_backend.dto;

import java.util.List;
import java.util.UUID;

public record SearchResponse(
    String question,
    int totalResults,
    List<ChunkResult> results
) {
    public record ChunkResult(
        UUID id,
        String content,
        String company,
        Integer year,
        String quarter,
        String docType,
        Integer pageNumber,
        String sourcePath
    ){}
}