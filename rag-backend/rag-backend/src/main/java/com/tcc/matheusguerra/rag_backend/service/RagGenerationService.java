package com.tcc.matheusguerra.rag_backend.service;
import java.util.LinkedHashSet;
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
    private final QueryIntentService intentService;
    private final ChatClient chatClient;

    private static final String SYSTEM_PROMPT = """
            Você é um assistente financeiro especializado em análise de relatórios de empresas
            listadas na bolsa de valores brasileira (B3).

            Diretrizes obrigatórias:
            1. Base exclusiva de contexto: Responda somente com base nos trechos de documentos
            fornecidos na mensagem do usuário. Não utilize conhecimento externo, não invente dados e não faça
            suposições além do que está explicitamente escrito nos trechos.

            2. Rastreabilidade obrigatória: Ao final de cada afirmação ou parágrafo, cite a
            referência de origem no formato [Empresa, Ano, Trimestre, Tipo do documento, Escopo, Página X].
            Exemplo: [Copel, 2025, 2T, release, COPEL DIS, Página 29].

            3. Dados insuficientes: Se a informação solicitada não estiver presente nos trechos fornecidos,
            responda: "Não possuo informações suficientes na documentação para responder esta pergunta.".
            Não tente adivinhar ou complementar com conhecimento próprio.

            4. Tom da conversa e idioma: Seja profissional, analítico e objetivo. Use linguagem clara
            e direta, adequada para investidores, analistas financeiros, e pessoas que possuem conhecimento
            básico ou intermidiário sobre o mercado financeiro. Suas respostas devem ser em português
            brasileiro, mesmo que a pergunta seja feita em outro idioma.

            5. Escala obrigatória: Todo valor monetário deve ser apresentado junto com a escala declarada
            no cabeçalho do trecho (campo "Escala"). Reproduza o número exatamente como aparece no documento;
            A única transformação permitida é tornar a escala explícita.
            Formato: "R$ 152.963 milhões (152.963, em R$ mil)".
            Se o campo Escala indicar "NAO DECLARADA NESTA PAGINA", NÃO suponha a unidade: informe
            explicitamente que o trecho recuperado não declara a escala do valor.
            Se a Escala vier seguida de "(nota de unidades do documento, nao desta pagina)", a unidade
            é válida e deve ser usada normalmente, MAS diga de onde ela vem - por exemplo: "R$ 1,380 bilhões
            (1.380.100, em R$ mil, conforme a nota de unidades do documento)". Isso não é formalidade: o leitor
            que for conferir o número na página citada não vai encontrar a unidade ali, e precisa saber que ela
            foi declarada na abertura do relatório.

            6. Escopo obrigatório: Todo valor deve identificar a entidade a que pertence, conforme o campo "Escopo"
            do trecho (por exemplo: Consolidado, COPEL DIS, COPEL GET, COPEL COM).
            Nunca apresente o resultado de uma subsidiária como se fosse o resultado consolidado do grupo, e nunca
            some valores de escopo diferentes. Se o campo Escopo indicar "NAO DECLARADO NESTA PAGINA", informe que 
            o trecho não identifica a entidade. Quando os trechos trouxerem escopos diferentes, separe-os em seções
            distintas na resposta.

            7. Coerência de período: Responda o período que foi perguntado. Se a pergunta não indicar período, use
            o período mais recente disponível nos trechos e diga explicitamente qual período está sendo usado. Não 
            empilhe períodos diferentes como se todos fossem a resposta. Exceção: se a mensagem do usuário trouxer a 
            observação de que o usuário pediu busca em todos os períodos, não se limite ao período mais recente: 
            reúna as informações dos trechos de todos os períodos recuperados e indique de qual período (trimestre e 
            ano) vem cada informação.

            8. Leitura de tabelas: Nos trechos marcados como tabela, o campo "Colunas" lista os rótulos das colunas
            na ordem em que os valores aparecem, e as células são separadas por "|". Atenção: a extração do PDF às
            vezes agrupa mais de um valor numa mesma célula (ex.: "LUCRO LÍQUIDO | 152.963 207.907 | (26,4)"). A ordem
            da esquerda para a direita é sempre confiável, mas as divisórias "|" não são. Portanto, conte os valores da 
            linha da esquerda para a direita a associe-os, na mesma ordem, aos rótulos listados em "Colunas" - ignorando
            o primeiro rótulo, que moneia a linha e não é um valor. Sempre diga a qual coluna (período) o valor que você
            citou pertence. Se a contagem de valores não bater com a de colunas, diga que não foi possível deteminar o 
            período com segurança em vez de escolher um.

            9. Múltiplas entidades: Se o campo Escopo indicar "multiplas empresas", o trecho é uma tabela comparativa com
            uma coluna por empresa (e geralmente uma coluna "Consolidado" ao final). Nesse caso não responda com um 
            número isolado sem identificar de qual coluna/empresa ele veio.

            10. Economia de resposta: responda a métrica que foi perguntada e pare. Não acrescente métricas correlatas
            que não foram pedidas (se a pergunta é sobre lucro líquido, não apresente também lucro recorrente, EBITDA ou
            receita).
            Quando o mesmo valor aparecer em dois trechos com escalas diferentes (por exemplo "152.963, em R$ mil" e 
            "153,0, em R$ milhões"), cite-o uma única vez, escolhendo o trecho de maior precisão - o de escala menor.
            Não repita o valor "também apresentado como". As regras 6 e 7 pedem que escopos e períodos diferentes fiquem
            em seções separadas: isso vale para os escopos e períodos que a pergunta abrange, não para enumerar tudo o 
            que foi recuperado. Uma resposta completa e curta é melhor do que uma exaustiva e cortada ao meio.

            11. Alcance declarado: se a resposta listar, comparar ou ordenar empresas, ela deve dizer quantas empresas
            foram examinadas e que as demais não foram avaliadas. Quando a mensagem do usuário trouxer uma "Observação 
            de cobertura", use os números dela - são fatos, não estimativas; Nunca invente quantas empresas existem no 
            acervo. Formato: "Entre as 5 empresas examinadas para esta pergunta (de 12 no acervo), ...", seguido de "As
            demais não foram avaliadas."
            Isto não é formalidade. Uma lista de "empresas que tiveram queda no lucro" construída a partir de 5 das 12
            é lida como se as outras 7 não tiveram tido queda - e essa é uma conclusão que os trechos não sustentam. O
            mesmo vale para qualquer ranking: diga sobre quantas empresas ele foi feito.
                """;

    public RagGenerationService(
            RagRetrievalService retrievalService,
            QueryIntentService intentService,
            ChatClient.Builder chatClientBuilder) {
        this.retrievalService = retrievalService;
        this.intentService = intentService;
        this.chatClient = chatClientBuilder.build();
    }
    public AskResponse ask(String question, int limit) {
       return ask(question, limit, null);
    }

    public AskResponse ask(String question, int limit, String corpus) {
       return ask(question, limit, corpus, false);
    }

    public AskResponse ask(String question, int limit, String corpus, boolean fullSearch) {
        log.info("Iniciando geração de resposta para \"{}\" (limite={} corpus={} buscaTotal={})", question, limit, corpus, fullSearch);

        SearchResponse searchResponse;
        try{
            searchResponse=retrievalService.search(question, limit, corpus,fullSearch);
        } catch (RetrievalUnavailableException exc){
            return new AskResponse(
                intentService.sanitizeQuestion(question), 
                falhaDoProvedor(exc, false), 
                List.of()
            );
        }

        List<SearchResponse.ChunkResult> chunks = searchResponse.results();
        String cleanedQuestion=searchResponse.question();
        log.info("A busca retornou {} chunks para compor o contexto", chunks.size());

        if (chunks.isEmpty()) {
            return emptyResult(cleanedQuestion);
        }

        String formattedContext = formatContext(chunks);
        log.info("Contexto formado com {} caracteres", formattedContext.length());

        String userMessage = buildUserMessage(cleanedQuestion, formattedContext, searchResponse.appliedFilters(), chunks, retrievalService.findAvailableCompanies().size(), fullSearch);

        List<AskResponse.SourceReference> sources = extractSources(chunks);

        log.info("Enviando requisição para o Gemini...");
        String generatedAnswer;
        try{
            org.springframework.ai.chat.model.ChatResponse resp = chatClient.prompt()
            .system(SYSTEM_PROMPT).user(userMessage).call().chatResponse();
            generatedAnswer=textoDe(resp);
            registrarDiagnostico(resp);
            if (foiTruncada(resp)){
                log.warn("Resposta truncada pelo limite de tokens para \"{}\"", cleanedQuestion);
                generatedAnswer=generatedAnswer + "\n\nAtenção: esta resposta foi interrompida ao atingir"
                + " o limite de tamanho do modelo e está incompleta.";
            }
        } catch(RuntimeException exc){
            log.error("Falha ao gerar a resposta para \"{}\": {}",cleanedQuestion, resumoTecnico(exc));
            log.debug("Detalhe tecnico da falha de geração", exc);
            return new AskResponse(cleanedQuestion, llmFailureMessage(exc), sources, null, searchResponse.appliedFilters());
        }
        log.info("Resposta gerada com sucesso ({} caracteres)", generatedAnswer==null?0:generatedAnswer.length());

        return new AskResponse(cleanedQuestion, generatedAnswer, sources, null, searchResponse.appliedFilters());
    }
    private static List<org.springframework.ai.chat.model.Generation> geracoesDe(org.springframework.ai.chat.model.ChatResponse resp){
        if (resp==null||resp.getResults()==null){
            return List.of();
        }
        return resp.getResults().stream().filter(g->g!=null && g.getOutput()!=null).toList();
    }
    private static boolean ehRaciocinio(org.springframework.ai.chat.model.Generation g){
        return Boolean.TRUE.equals(g.getOutput().getMetadata().get("isThought"));
    }
    private static String textoDe(org.springframework.ai.chat.model.ChatResponse resp){
        return geracoesDe(resp).stream().filter(g->!ehRaciocinio(g))
            .map(g->g.getOutput().getText()).filter(texto->texto!=null)
            .collect(Collectors.joining());
    }
    private static boolean foiTruncada(org.springframework.ai.chat.model.ChatResponse resp){
       return geracoesDe(resp).stream().map(g->g.getMetadata()==null
            ? null : g.getMetadata().getFinishReason()).filter(motivo -> motivo!=null)
            .map(motivo->motivo.toUpperCase(java.util.Locale.ROOT))
            .anyMatch(m->m.contains("MAX_TOKEN")||m.contains("LENGTH"));
    }
    private static void registrarDiagnostico(org.springframework.ai.chat.model.ChatResponse resp){
        List<org.springframework.ai.chat.model.Generation> geracoes = geracoesDe(resp);
        long raciocinio = geracoes.stream().filter(RagGenerationService::ehRaciocinio).count();
        String motivos = geracoes.stream().map(g->g.getMetadata()==null
            ?null : g.getMetadata().getFinishReason()).filter(motivo->motivo!=null)
            .distinct().collect(Collectors.joining(", "));
        org.springframework.ai.chat.metadata.Usage uso = resp == null || resp.getMetadata() == null
            ? null:resp.getMetadata().getUsage();
        log.info("Resposta do modelo: {} parte(s) ({} de raciocínio), término=[{}], tokens entrada={} saida={} total={}",
            geracoes.size(), raciocinio, motivos,
            uso ==null ? "?":uso.getPromptTokens(),
            uso ==null ? "?":uso.getCompletionTokens(),
            uso ==null ? "?":uso.getTotalTokens()
        );
    }
    public static String resumoTecnico(Throwable exc){
        String raw = cadeiaDeMensagens(exc);
        String detail = raw.toLowerCase(java.util.Locale.ROOT);
        StringBuilder sb = new StringBuilder();
        if(ehIndisponibilidade(detail)){
            sb.append(" serviço indisponível ou sobrecarregado (HTTP 503)");
        } else if (ehCotaExcedida(detail)){
            sb.append(" cota de uso excedida (HTTP 429)");
        } else if (ehTempoEsgotado(detail)){
            sb.append(" tempo limite de resposta excedido");
        } else {
            Throwable raiz=exc;
            while(raiz.getCause() != null && raiz.getCause() != raiz){
                raiz = raiz.getCause();
            }
            sb.append(" falha não classificada (tipo: )").append(raiz.getClass().getSimpleName()).append(")");
        }
        String modelo = extrairModelo(raw);
        String espera = extrair(raw, "retry in ([0-9.]+)s");
        if (modelo!=null||espera!=null){
            sb.append(" [");
            if (modelo!=null){
                sb.append("modelo=").append(modelo);
            }
            if (espera!=null){
                sb.append(modelo!=null ? ", ":"").append("aguardar ").append(espera).append('s');
            }
            sb.append(']');
        }
        return sb.toString();
    }
    private static String extrair(String texto, String padrao){
        java.util.regex.Matcher m = java.util.regex.Pattern.compile(padrao, java.util.regex.Pattern.CASE_INSENSITIVE).matcher(texto);
        return m.find() ? m.group(1) : null;
    }
    private static String extrairModelo (String texto){
        String modelo = extrair(texto, "\"modelo\"\\s*:\\s*\"([^\"]+)\"");
        return modelo != null ? modelo : extrair(texto, "model:\\s*([A-Za-z0-9.\\-]+)");
    }
    public static String cadeiaDeMensagens(Throwable exc){
        StringBuilder chain = new StringBuilder();
        for (Throwable t = exc; t!=null && chain.length() < 4000; t = t.getCause()){
            chain.append(t.getClass().getSimpleName()).append(' ').append(String.valueOf(t.getMessage())).append(' ');
            if (t.getCause() == t){
                break;
            }
        }
        return chain.toString();
    }
    private static boolean ehIndisponibilidade(String detail){
        return detail.contains("503")||detail.contains("high demand")||detail.contains("unavailable")||detail.contains("overloaded");
    }
    private static boolean ehCotaExcedida(String detail){
        return detail.contains("429")||detail.contains("quota")||detail.contains("resource_exhausted")||detail.contains("rate limit");
    }
    private static boolean ehTempoEsgotado(String detail){
        return detail.contains("timeout")||detail.contains("deadline");
    }
    public static String llmFailureMessage(Throwable exc){
        return falhaDoProvedor(exc, true);
    }
    public static String falhaDoProvedor(Throwable exc, boolean comFontes){
        String servico = comFontes ? "O modelo de linguagem":"O serviço de embeddings";
        String raw = cadeiaDeMensagens(exc);
        String detail = raw.toLowerCase(java.util.Locale.ROOT);
        if(ehIndisponibilidade(detail)){
            return servico + " está indisponível no momento.";
        }
        if (ehCotaExcedida(detail)){
            String modelo = extrairModelo(detail);
            StringBuilder msg = new StringBuilder("A cota de uso").append(comFontes 
                ? " do modelo de linguagem": " do serviço de embeddings"
            );
            if(modelo!=null){
                msg.append(" (").append(modelo).append(") ");
            }
            return msg.append(" foi atingida.").toString();
        }
        if(ehTempoEsgotado(detail)){
            return servico+" não respondeu dentro do tempo limite.";
        }
        return "Não foi possível concluir a consulta por uma falha na chamada ao provedor.";
    }
    private AskResponse emptyResult(String question){
        log.warn("Nenhum chunk relevante encontrado para a pergunta: \"{}\"", question);
        List<String> availableCompanies = retrievalService.findAvailableCompanies();
        log.info("Empresas disponíveis na base: {}", availableCompanies);
        String fallbackMessage;
        if (availableCompanies.isEmpty()){
            fallbackMessage="Não foram encontrados documentos na base de dados. \n"
            +"Verifique se o processo de ingestão foi executado corretamente.";
        } else {
            String companiesList=String.join(", ", availableCompanies);
            fallbackMessage = "Não foram encontrados documentos relevantes para esta pergunta. \n"
                + "As empresas disponíveis na base são: "+ companiesList 
                + ".\nGostaria de reformular sua pergunta sobre alguma delas?";
        }
        return new AskResponse(question, fallbackMessage, List.of(), availableCompanies);
    }
    public List<String>findAvailableCompanies(){
        return retrievalService.findAvailableCompanies();
    }
    private String nullSafe(Object value){
        return value != null ? value.toString() : "N/A";
    }
    private String formatContext(List<SearchResponse.ChunkResult>chunks){
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i<chunks.size();i++){
            SearchResponse.ChunkResult chunk = chunks.get(i);
            sb.append("--- Trecho ").append(i+1).append(" ---\n");
            sb.append("[Empresa: ").append(nullSafe(chunk.company()));
            sb.append(" | Ano: ").append(nullSafe(chunk.year()));
            sb.append(" | Trimestre: ").append(nullSafe(chunk.quarter()));
            sb.append(" | Tipo: ").append(nullSafe(chunk.docType()));
            sb.append(" | Escopo: ").append(scopeLabel(chunk.scope()));
            sb.append(" | Escala: ").append(scaleLabel(chunk.scale(), chunk.currency()));
            if (chunk.scale() != null && "documento".equals(chunk.scaleSource())){
                sb.append(" (nota de unidades do documento, não desta pagina)");
            }
            sb.append(" | Conteudo: ").append(nullSafe(chunk.contentType()));
            sb.append(" | Página: ").append(nullSafe(chunk.pageNumber()));
            sb.append("]\n");
            sb.append(chunk.content()).append("\n\n");
        }
        return sb.toString();
    }
    private String scopeLabel(String scope){
        return scope == null || scope.isBlank() ? "NAO DECLARADO NESTA PAGINA" : scope;
    }
    private String scaleLabel(String scale, String currency){
        if (scale == null || scale.isBlank()){
            return "NAO DECLARADA NESTA PAGINA";
        }
        String symbol = "USD".equalsIgnoreCase(currency) ? "US$" : "R$";
        return switch (scale){
            case "mil" -> symbol + " mil (milhares)";
            case "milhoes" -> symbol + " milhões";
            case "bilhoes" -> symbol + " bilhões";
            case "energia" -> "unidades de energia";
            default -> scale;
        };
    }
    private String buildUserMessage(String question, String formattedContext, SearchResponse.AppliedFilters filters,
        List<SearchResponse.ChunkResult> chunks, int totalNoAcervo, boolean fullSearch) 
    {
            String coberturaNote = coberturaNote(chunks, totalNoAcervo);
            String periodNote ="";
            boolean semPeriodo= filters == null || ((filters.years()==null||filters.years().isEmpty())
                && (filters.quarters()==null||filters.quarters().isEmpty()));
            if (filters != null && filters.periodWasInferred()){
                periodNote = """
                        Observação: a pergunta não indicou um período. Os trechos abaixo foram restreitos ao período mais recente disponível para esta empresa
                        (%s%s). Informe isso ao usuário na sua resposta.
                        """.formatted(nullSafe(filters.quarter()), nullSafe(filters.year()));
            } else if (fullSearch && semPeriodo){
                periodNote="""
                    Observação: o usuário pediu busca em todos os períodos. Os trechos encontrados podem vir de trimestres diferentes.
                """;
            }
            return """
                    %s%sContexto dos relatórios financeiros:
                    %s
                    Pergunta do usuário:
                    %s
                    """.formatted(coberturaNote, periodNote, formattedContext, question);
    }
    private String coberturaNote(List<SearchResponse.ChunkResult> chunks, int totalNoAcervo){
        if (chunks == null || chunks.isEmpty() || totalNoAcervo <= 1){
            return  "";
        }
        List<String> examinadas = chunks.stream()
            .map(SearchResponse.ChunkResult::company)
            .filter(c->c!=null && !c.isBlank())
            .distinct()
            .sorted()
            .toList();
        if (examinadas.size() <= 1 || examinadas.size() >= totalNoAcervo){
            return "";
        }
        return """
                Observação de cobertura: os trechos abaixo vêm de %d empresas (%s), de um acervo
                com %d. As demais não foram examinadas para esta pergunta.
                Se a sua resposta listar, comparar ou ordenar empresas, diga explicitamente quantas
                foram examinadas e que as demais não foram avaliadas, uma lista parcial apresentada
                sem essa ressalva e lida como se fosse completa.
                """.formatted(examinadas.size(), String.join(", ", examinadas), totalNoAcervo);
    }
    private List<AskResponse.SourceReference> extractSources(List<SearchResponse.ChunkResult> chunks){
        return chunks.stream()
            .map(chunk -> new AskResponse.SourceReference(
                chunk.company(),
                chunk.year(),
                chunk.quarter(),
                chunk.docType(),
                chunk.pageNumber(),
                chunk.scope(),
                chunk.scale(),
                chunk.scaleSource()))
            .collect(Collectors.toCollection(LinkedHashSet::new))
            .stream()
            .toList();
    }
}