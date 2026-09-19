package com.tcc.matheusguerra.rag_backend.controller;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import com.tcc.matheusguerra.rag_backend.dto.AskRequest;
import com.tcc.matheusguerra.rag_backend.dto.AskResponse;
import com.tcc.matheusguerra.rag_backend.service.RagGenerationService;

@RestController
@RequestMapping("/api/ask")
public class GenerationController{
    private final RagGenerationService generationService;
    public GenerationController(RagGenerationService generationService){
        this.generationService = generationService;
    } 
    @GetMapping
    public ResponseEntity<AskResponse> askGet(
        @RequestParam String question,
        @RequestParam(defaultValue = "5") int limit
    ){
        AskResponse response = generationService.ask(question, limit);
        return ResponseEntity.ok(response);
    }

    @PostMapping
    public ResponseEntity<AskResponse> askPost(@RequestBody AskRequest request){
        AskResponse response = generationService.ask(request.question(), request.limit());
        return ResponseEntity.ok(response);
    }
}