package com.tcc.matheusguerra.rag_backend.dto;

import java.util.List;

public record AskResponse(
        String question,
        String answer,
        List<SourceReference> sources,
        List<String> availableCompanies,
        SearchResponse.AppliedFilters appliedFilters) {
    public record SourceReference(
            String company, Integer year, String quarter, String docType, Integer pageNumber,
            String scope, String scale, String scaleSource) {
    }

    public AskResponse(String question, String answer, List<SourceReference> sources) {
        this(question, answer, sources, null);
    }

    public AskResponse(String question, String answer, List<SourceReference> sources, List<String> availableCompanies) {
        this(question, answer, sources, availableCompanies, null);
    }
}