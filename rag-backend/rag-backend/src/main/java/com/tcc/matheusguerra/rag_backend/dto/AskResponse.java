package com.tcc.matheusguerra.rag_backend.dto;

import java.util.List;

public record AskResponse(
    String question,
    String answer,
    List<SourceReference> sources,
    List<String> availableCompanies
) {
    public record SourceReference(
        String company, Integer year, String quarter, String docType, Integer pageNumber
    ) {
    }
    
    public AskResponse(String question, String answer, List<SourceReference> sources){
        this(question, answer, sources, null);
    }
}