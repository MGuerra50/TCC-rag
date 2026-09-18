package com.tcc.matheusguerra.rag_backend.dto;

import java.util.List;

public record AskResponse(
    String question,
    String answer,
    List<SourceReference> sources
) {
    public record SourceReference(
        String company, Integer year, String quarter, String docType, Integer pageNumber
    ) {
    }
}