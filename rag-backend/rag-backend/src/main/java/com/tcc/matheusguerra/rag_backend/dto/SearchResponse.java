package com.tcc.matheusguerra.rag_backend.dto;

import java.util.List;
import java.util.UUID;

public record SearchResponse(
    String question,
    int totalResults,
    List<ChunkResult> results,
    AppliedFilters appliedFilters
) {
    public record ChunkResult(
        UUID id,
        String content,
        String company,
        Integer year,
        String quarter,
        String docType,
        Integer pageNumber,
        String printedPageLabel,
        String sourcePath,
        String sectionTitle,
        String scope,
        String scale,
        String scaleSource,
        String currency,
        String contentType,
        Double distance,
        Double score
    ){}

    public record AppliedFilters(
        List<String> companies,
        List<Integer> years,
        List<String> quarters,
        List<String> scopes,
        boolean periodWasInferred
    ){
        public String quarter() {return quarters == null || quarters.isEmpty() ? null : quarters.get(0);}
        public Integer year() {return years == null || years.isEmpty() ? null : years.get(0);}
    }

    public SearchResponse(String question, int totalResults, List<ChunkResult> results){
        this(question, totalResults, results, null);
    }
}