package com.tcc.matheusguerra.rag_backend.controller;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import com.tcc.matheusguerra.rag_backend.dto.SearchResponse;
import com.tcc.matheusguerra.rag_backend.dto.SearchRequest;
import com.tcc.matheusguerra.rag_backend.service.RagRetrievalService;

@RestController
@RequestMapping("/api/search")
public class RetrievalController {
    private final RagRetrievalService service;
    public RetrievalController (RagRetrievalService service){
        this.service = service;
    } 

    @GetMapping
    public ResponseEntity<SearchResponse> search (
        @RequestParam String question,
        @RequestParam(defaultValue = "5") int limit,
        @RequestParam(required = false) String corpus
    ){
        SearchResponse response = corpus == null || corpus.isBlank()
            ? service.search(question, limit)
            : service.search(question, limit, corpus);
        return ResponseEntity.ok(response);
    }

    @PostMapping
    public ResponseEntity<SearchResponse> searchPost(@RequestBody SearchRequest request){
        SearchResponse response = service.search(request.question(), request.limit());
        return ResponseEntity.ok(response);
    }
}