package com.tcc.matheusguerra.rag_backend.service;

import java.util.List;
import java.util.stream.Collectors;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.stereotype.Service;
import com.tcc.matheusguerra.rag_backend.dto.AskResponse;
import com.tcc.matheusguerra.rag_backend.dto.SearchResponse;

@Service
public class RagGenerationService {
    private static final Logger log = LoggerFactory.getLogger(RagGenerationService.class);
    private final RagRetrievalService retrievalService;
    private final ChatClient chatClient;

    private static final String SYSTEM_PROMPT = """
            Você é um assistente financeiro especializado em análise de relatórios de empresas
            listadas na bolsa de valores brasileira (B3).

            Diretrizes obrigatórias:
            1. Base exclusiva de contexto: Responda somente com base nos trechos de documentos
            fornecidos abaixo. Não utilize conhecimento externo, não invente dados e não faça
            suposições além do que está explicitamente escrito nos trechos.

            2. Rastreabilidade obrigatória: Ao final de cada afirmação ou parágrafo, cite a
            referência de origem no formato [Empresa, Ano, Trimestre, Tipo do documento, Página X].
            Exemplo: [PETR4, 2023, 3T, release, Página 12].

            3. Dados insuficientes: Se a informação solicitada não estiver presente nos trechos fornecidos,
            responda: "Não possuo informações suficientes na documentação para responder esta pergunta.".
            Não tente adivinhar ou complementar com conhecimento próprio.

            4. Tom da conversa e idioma: Seja profissional, analítico e objetivo. Use linguagem clara
            e direta, adequada para investidores, analistas financeiros, e pessoas que possuem conhecimento
            básico ou intermidiário sobre o mercado financeiro. Suas respostas devem ser em português
            brasileiro, mesmo que a pergunta seja feita em outro idioma.

            5. Precisão: Ao citar números, valores monetários ou percentuais, reproduza exatamente como aparecem
            nos trechos fornecidos. Não arredonde nem converta unidades por conta própria.
                """;

    public RagGenerationService(
            RagRetrievalService retrievalService,
            ChatClient.Builder chatClientBuilder) {
        this.retrievalService = retrievalService;
        this.chatClient = chatClientBuilder.build();
    }

    public AskResponse ask(String question, int limit) {
        log.info("Iniciando geração de resposta para \"{}\" (limit={})", question, limit);

        SearchResponse searchResponse = retrievalService.search(question, limit);
        List<SearchResponse.ChunkResult> chunks = searchResponse.results();
        log.info("Retrieval retornou {} chunks compor o contexto", chunks.size());

        if (chunks.isEmpty()) {
            log.warn("Nenhum chunk encontrado para a pergunta: \"{}\"", question);
            return new AskResponse(
                    question,
                    "Não foram encontrados documentos relevantes para responder esta pergunta",
                    List.of());
        }

        String formattedContext = formatContext(chunks);
        log.info("Contexto formado com {} caracteres", formattedContext.length());

        String userMessage = buildUserMessage(question, formattedContext);

        log.info("Enviando requisição para o Gemini...");
        String generatedAnswer = chatClient.prompt()
                .system(SYSTEM_PROMPT)
                .user(userMessage)
                .call()
                .content();

        log.info("Resposta gerada com sucesso ({} caracteres)", generatedAnswer.length());
        List<AskResponse.SourceReference> sources = extractSources(chunks);
        return new AskResponse(question, generatedAnswer, sources);
    }

    private String nullSafe(Object value) {
        return value != null ? value.toString() : "N/A";
    }

    private String formatContext(List<SearchResponse.ChunkResult> chunks) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < chunks.size(); i++) {
            SearchResponse.ChunkResult chunk = chunks.get(i);
            sb.append("Trecho ").append(i + 1).append("\n");
            sb.append("[Empresa: ").append(nullSafe(chunk.company()));
            sb.append("| Ano: ").append(nullSafe(chunk.year()));
            sb.append("| Trimestre: ").append(nullSafe(chunk.quarter()));
            sb.append("| Tipo: ").append(nullSafe(chunk.docType()));
            sb.append("| Página: ").append(nullSafe(chunk.pageNumber()));
            sb.append("]\n");
            sb.append(chunk.content()).append("\n");
        }
        return sb.toString();
    }

    private String buildUserMessage(String question, String formattedContext) {
        return """
                Contexto dos relatórios financeiros:

                %s

                Pergunta do usuário:

                %s
                """.formatted(formattedContext, question);
    }

    private List<AskResponse.SourceReference> extractSources(List<SearchResponse.ChunkResult> chunks) {
        return chunks.stream().map(chunk -> new AskResponse.SourceReference(
                chunk.company(),
                chunk.year(),
                chunk.quarter(),
                chunk.docType(),
                chunk.pageNumber())).collect(Collectors.toList());
    }
}