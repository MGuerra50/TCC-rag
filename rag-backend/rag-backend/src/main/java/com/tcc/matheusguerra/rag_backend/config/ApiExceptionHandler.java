package com.tcc.matheusguerra.rag_backend.config;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import com.tcc.matheusguerra.rag_backend.service.RagGenerationService;
import com.tcc.matheusguerra.rag_backend.service.RetrievalUnavailableException;

@RestControllerAdvice 
public class ApiExceptionHandler {
    private static final Logger log = LoggerFactory.getLogger(ApiExceptionHandler.class);
    
    @ExceptionHandler(RetrievalUnavailableException.class)
    public ResponseEntity<Map<String, Object>> provedorIndisponivel(RetrievalUnavailableException exc){
        log.error("Busca indisponivel: {}", RagGenerationService.resumoTecnico(exc));
        log.debug("Detalhe técnico", exc);
        return corpo(HttpStatus.SERVICE_UNAVAILABLE,
            RagGenerationService.falhaDoProvedor(exc, false)
        );
    }
    @ExceptionHandler (DataAccessException.class)
    public ResponseEntity<Map<String, Object>> bancoIndisponivel(DataAccessException exc){
        log.error("Banco de dados indisponivel: {}", RagGenerationService.resumoTecnico(exc));
        log.debug("Detalhe técnico", exc);
        return corpo(HttpStatus.SERVICE_UNAVAILABLE,
            "O banco de dados não está acessível no momento."
        );
    }

    private ResponseEntity<Map<String, Object>> corpo(HttpStatus status, String mensagem){
        Map<String, Object> body=new LinkedHashMap<>();
        body.put("timestamp", Instant.now().toString());
        body.put("status", status.value());
        body.put("error", status.getReasonPhrase());
        body.put("message", mensagem);
        return ResponseEntity.status(status).body(body);
    }
}
