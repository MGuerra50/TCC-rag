package com.tcc.matheusguerra.rag_backend.dto;

public record AskRequest(
    String question,
    Integer limit
) {
    public AskRequest{
        if(limit == null || limit <= 0){
            limit = 5;
        }
    }
}