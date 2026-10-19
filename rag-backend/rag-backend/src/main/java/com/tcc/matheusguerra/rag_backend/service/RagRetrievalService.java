package com.tcc.matheusguerra.rag_backend.service;

import java.util.List;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Collectors;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.embedding.EmbeddingModel;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import com.tcc.matheusguerra.rag_backend.dto.SearchResponse;
import com.tcc.matheusguerra.rag_backend.repository.ChunkWithScore;
import com.tcc.matheusguerra.rag_backend.repository.DocumentChunkRepository;
import com.tcc.matheusguerra.rag_backend.repository.DocumentChunkV2Repository;

@Service
public class RagRetrievalService {
    private static final Logger log = LoggerFactory.getLogger(RagRetrievalService.class);
    public static final String CORPUS_V1 = "v1";
    public static final String CORPUS_V2 = "v2";
    private final DocumentChunkV2Repository repository;
    private final DocumentChunkRepository legacyRepository;
    private final EmbeddingModel embeddingModel;
    private final QueryIntentService intentService;
    private final double maxDistance;
    private final int candidatePool;
    private final String defaultCorpus;

    public RagRetrievalService(
        DocumentChunkV2Repository repository, 
        DocumentChunkRepository legacyRepository, 
        EmbeddingModel embeddingModel,
        QueryIntentService intentService,
        @Value("${rag.retrieval.max-distance:1.2}") double maxDistance,
        @Value("${rag.retrieval.candidate-pool:30}") int candidatePool,
        @Value("${rag.retrieval.corpus:v2}") String defaultCorpus
    ) {
        this.repository = repository;
        this.legacyRepository = legacyRepository;
        this.embeddingModel = embeddingModel;
        this.intentService = intentService;
        this.maxDistance = maxDistance;
        this.candidatePool = candidatePool;
        this.defaultCorpus = defaultCorpus;
    }

    public SearchResponse search(String question, int limit){
        return search(question, limit, defaultCorpus);
    }

    public SearchResponse search(String question, int limit, String corpus){
        return search(question, limit, corpus, false);
    }

    public SearchResponse search(String question, int limit, String corpus, boolean fullSearch) {
        if (corpus == null || corpus.isBlank()){
            corpus = defaultCorpus;
        }
        String cleaned = intentService.sanitizeQuestion(question);
        if (CORPUS_V1.equalsIgnoreCase(corpus)){
            return searchLegacy(cleaned, limit);
        }
        QueryIntent intent = resolveIntent(cleaned, fullSearch);
        return search(cleaned, limit, intent);
    }

    private float[] embedQuestion(String question){
        try{
            return embeddingModel.embed(question);
        } catch (RuntimeException exc){
            log.error("Falha ao converter a pergunta em embedding: {}",
                RagGenerationService.resumoTecnico(exc)
            );
            log.debug("Detalhe técnico da falha de embedding da pergunta", exc);
            throw new RetrievalUnavailableException("Não foi possível converter a pergunta em embedding", exc);
        }
    }

    private SearchResponse searchLegacy(String question, int limit){
        log.info("Busca legado (v1, sem filtros) para \"{}\" limit={}", question, limit);
        float[] vector = embedQuestion(question);
        List<ChunkWithScore> chunks = legacyRepository.findSimilarChunks(formatVectorForPgVector(vector), limit, maxDistance);
        log.info("Busca v1 retornou {} chunks", chunks.size());
        return buildResponse(question, chunks, QueryIntent.empty());
    }

    public QueryIntent resolveIntent(String question){
        return resolveIntent(question, false);
    }

    public QueryIntent resolveIntent(String question, boolean fullSearch){
        QueryIntent intent = intentService.extract(question, findAvailableCompanies());
        if (intent.hasPeriod() || intent.company() == null){
            return intent;
        }
        if(fullSearch){
            log.info("Busca em todos os períodos para {}; período mais recente não será aplicado", intent.company());
            return intent;
        }
        List<Object[]> latest = repository.findLatestPeriod(intent.company());
        if (latest.isEmpty()){
            return intent;
        }
        Object[] row = latest.get(0);
        Integer year = row[0] == null ? null : ((Number) row[0]).intValue();
        String quarter = row[1] == null ? null : row[1].toString();
        log.info("Nenhum período informado para {}; Usando o mais recente: {}{}",
            intent.company(), quarter, year
        );
        return intent.withPeriod(year, quarter, true);
    }
    public SearchResponse search(String question, int limit, QueryIntent intent){
        List<QueryIntent.Variant> variants = intent.variants();
        log.info("Busca híbrida \"{}\" limit={} filtros={} variantes={}", question, limit, intent, variants.size());
        float[] vector = embedQuestion(question);
        String pgVectorString = formatVectorForPgVector(vector);
        int poolSize=Math.max(candidatePool, limit);
        Map<UUID, ChunkWithScore> merged = new LinkedHashMap<>();
        for (QueryIntent.Variant v : variants){
            List<ChunkWithScore> parcial = repository.findSimilarChunksFiltered(pgVectorString, question, v.company(), v.year(), v.quarter(), v.scope(), poolSize, limit, maxDistance);
            for (ChunkWithScore c : parcial){
                merged.putIfAbsent(c.getId(), c);
            }
            if (variants.size() > 1){
                log.info(" variante [{}{}{}] -> {} chunks",
                    v.quarter() == null ? "*" : v.quarter(),
                    v.year() == null ? "" : "/" + v.year(),
                    v.scope() == null ? "" : " " + v.scope(),
                    parcial.size()
                );
            }
        }
        List<ChunkWithScore> chunks = new ArrayList<>(merged.values());
        chunks.sort(Comparator.comparingDouble(
            (ChunkWithScore c) -> c.getScore() == null ? 0.0 : c.getScore()
        ).reversed());
        int teto = limit * Math.max(1, variants.size());
        if (chunks.size()>teto){
            chunks = new ArrayList<>(chunks.subList(0, teto));
        }
        log.info("Busca retornou {} chunks de {} variante(s) (candidatos={} distancia máxima={})", chunks.size(),
            variants.size(), poolSize, maxDistance);    
        return buildResponse(question, chunks, intent);
    }
    public List<String> findAvailableCompanies(){
        return repository.findDistinctCompanies();
    }
    private String formatVectorForPgVector(float[] vector){
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < vector.length; i++){
            if (i>0){
                sb.append(",");
            }
            sb.append(vector[i]);
        }
        sb.append("]");
        return sb.toString();
    }

    private SearchResponse buildResponse (String question, List<ChunkWithScore> chunks, QueryIntent intent){
        List<SearchResponse.ChunkResult> results = chunks.stream()
            .map(chunk->new SearchResponse.ChunkResult(
                chunk.getId(),
                chunk.getContent(),
                chunk.getCompany(),
                chunk.getYear(),
                chunk.getQuarter(),
                chunk.getDocType(),
                chunk.getPageNumber(),
                chunk.getPrintedPageLabel(),
                chunk.getSourcePath(),
                chunk.getSectionTitle(),
                chunk.getScope(),
                chunk.getScale(),
                chunk.getScaleSource(),
                chunk.getCurrency(),
                chunk.getContentType(),
                chunk.getDistance(),
                chunk.getScore()
            ))
            .collect(Collectors.toList());
        SearchResponse.AppliedFilters filters = new SearchResponse.AppliedFilters(
            intent.companies(),
            intent.years(),
            intent.quarters(),
            intent.scopes(),
            intent.periodWasInferred()  
        );
        return new SearchResponse(question, results.size(), results, filters);
    }
}