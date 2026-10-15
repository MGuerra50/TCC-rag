package com.tcc.matheusguerra.rag_backend.dto;

public record AskRequest(
    String question,
    Integer limit,
    String corpus
) {
    public AskRequest{
        if(limit == null || limit <= 0){
            limit = 5;
        }
    }
    public AskRequest(String question, Integer limit){
        this(question, limit, null);
    }
}