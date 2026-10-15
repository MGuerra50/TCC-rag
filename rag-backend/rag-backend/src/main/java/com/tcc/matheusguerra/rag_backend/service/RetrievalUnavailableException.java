package com.tcc.matheusguerra.rag_backend.service;

public class RetrievalUnavailableException extends RuntimeException {
    public RetrievalUnavailableException(String message, Throwable cause){
        super(message, cause);
    }    
}
