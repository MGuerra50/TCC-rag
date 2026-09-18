package com.tcc.matheusguerra.rag_backend.dto;

record SearchRequest(
        String question,
        Integer limit) {
    SearchRequest {
        if (limit == null || limit <= 0) {
            limit = 5;
        }
    }
}