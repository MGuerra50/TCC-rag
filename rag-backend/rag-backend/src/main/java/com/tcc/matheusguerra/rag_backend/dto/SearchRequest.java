package com.tcc.matheusguerra.rag_backend.dto;

public record SearchRequest(
        String question,
        Integer limit) {
    public SearchRequest {
        if (limit == null || limit <= 0) {
            limit = 5;
        }
    }
}