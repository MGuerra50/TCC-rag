package com.tcc.matheusguerra.rag_backend.dto;

public record AskRequest(
    String question,
    Integer limit,
    String corpus,
    Boolean fullSearch
) {
    public AskRequest{
        if(limit == null || limit <= 0){
            limit = 5;
        }
        if (fullSearch == null){
            fullSearch = false;
        }
    }
    public AskRequest(String question, Integer limit){
        this(question, limit, null, false);
    }
}