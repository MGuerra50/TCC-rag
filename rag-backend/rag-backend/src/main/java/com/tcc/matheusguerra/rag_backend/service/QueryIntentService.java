package com.tcc.matheusguerra.rag_backend.service;
import java.text.Normalizer;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

@Service 
public class QueryIntentService {
    private static final Logger log = LoggerFactory.getLogger(QueryIntentService.class);
    private static final Pattern QUARTER_COMPACT=Pattern.compile(
        "(?<!\\d)([1-4])T(\\d{2}|\\d{4})(?!\\d)", Pattern.CASE_INSENSITIVE
    );
    private static final Pattern QUARTER_WORDS=Pattern.compile(
        "([1-4])\\S*(?:o|a|º|ª)?\\s*trimestre", Pattern.CASE_INSENSITIVE
    );
    private static final Map<String, String> ORDINAL_WORDS = Map.of(
        "primeiro", "T1", "segundo", "T2", "terceiro", "T3", "quarto", "T4"
    );
    private static final Pattern ORDINAL_QUARTER=Pattern.compile(
        "(primeiro|segundo|terceiro|quarto)\\s+trimestre", Pattern.CASE_INSENSITIVE
    );
    private static final Pattern YEAR=Pattern.compile(
        "(?<!\\d)(19\\d{2}|20\\d{2})(?!\\d)"
    );
    private static final Pattern HALF_YEAR=Pattern.compile(
        "(?<!\\d)([12])S(\\d{2}|\\d{4})(?!\\d)", Pattern.CASE_INSENSITIVE
    );
    private static final List<Map.Entry<Pattern, String>> SCOPE_KEYWORDS = List.of(
        Map.entry(Pattern.compile("\\bconsolidad[oa]\\b", Pattern.CASE_INSENSITIVE), "consolidado"),
        Map.entry(Pattern.compile("\\bdistribui[cç][aã]o\\b|copel\\s+dis\\b|\\bdis\\b" , Pattern.CASE_INSENSITIVE), "%DIS%"),
        Map.entry(Pattern.compile("\\bgera[cç][aã]o\\s+e\\s+transmiss[aã]o\\b|copel\\s+get\\b|\\bget\\b" , Pattern.CASE_INSENSITIVE), "%GET%"),
        Map.entry(Pattern.compile("(?i:\\bcomercializa[cç][aã]o\\b)|(?i:copel)\\s+COM\\b"), "%COM %"));

    private static final Pattern LIMIT_SUFIX=Pattern.compile(
        "[%&?]limit=\\d+\\s*$", Pattern.CASE_INSENSITIVE
    );
    public String sanitizeQuestion(String question){
        if (question == null){
            return "";
        }
        String cleaned = LIMIT_SUFIX.matcher(question.trim()).replaceAll("").trim();
        if (!cleaned.equals(question.trim())){
            log.warn("Sufixo de limit removido da pergunta: \"{}\" -> \"{}\"", question, cleaned);
        }
        return cleaned;
    }
    public QueryIntent extract(String question, List<String> availableCompanies){
        if (question == null || question.isBlank()){
            return QueryIntent.empty();
        }
        String flat = normalize(question);
        List<String> companies= matchCompanies(flat, availableCompanies);
        List<String> quarters = matchQuarters(question, flat);
        List<Integer> year = matchYears(question);
        List<String> scopes = matchScopes(question);
        QueryIntent intent = new QueryIntent(companies, year, quarters, scopes, false);
        log.info("Intenção extraída: empresas={} anos={} trimestres={} escopos={} ({} variante(s))",
            companies, year, quarters, scopes, intent.variants().size()
        );
        return intent;
    }
    private List<String> matchCompanies(String flatQuestion, List<String> availableCompanies){
        if (availableCompanies==null||availableCompanies.isEmpty()){
            return List.of();
        }
        List<String>found=new ArrayList<>();
        for (String candidate : availableCompanies){
            if(candidate == null || candidate.isBlank()){
                continue;
            }
            if (flatQuestion.contains(normalize(candidate)) || matchesShortForm(flatQuestion, candidate, availableCompanies)){
                found.add(candidate);
            }
        }
        found.sort(Comparator.comparingInt((String c)-> normalize(c).length()).reversed());
        return found;
    }
    private boolean matchesShortForm(String flatQuestion, String candidate, List<String> availableCompanies){
        String curto = shortForm(candidate);
        if (curto.length() < 4 || curto.equals(normalize(candidate))){
            return false;
        }
        long colisoes=availableCompanies.stream().filter(c->c!=null&&!c.isBlank()).filter(c->shortForm(c).equals(curto)).count();
        if (colisoes>1){
            return false;
        }
        return Pattern.compile("\\b"+Pattern.quote(curto)+"\\b").matcher(flatQuestion).find();
    }
    private String shortForm(String canditade){
        String flat = normalize(canditade).trim();
        int espaco = flat.indexOf(' ');
        return espaco < 0 ? flat : flat.substring(0, espaco);
    }
    private List<String> matchQuarters(String original, String flat){
        List<String> found = new ArrayList<>();
        Matcher compact = QUARTER_COMPACT.matcher(original);
        while(compact.find()){
            add(found, compact.group(1) + "T");
        }
        Matcher half = HALF_YEAR.matcher(original);
        while(half.find()){
            add(found, "1".equals(half.group(1)) ? "2T": "4T");
        }
        if (!found.isEmpty()){
            return found;
        }
        Matcher words = QUARTER_WORDS.matcher(flat);
        while(words.find()){
            add(found, words.group(1) + "T");
        }
        Matcher ordinal = ORDINAL_QUARTER.matcher(flat);
        while(ordinal.find()){
            add(found, ORDINAL_WORDS.get(ordinal.group(1).toLowerCase(Locale.ROOT)));
        }
        return found;
    }
    private List<Integer> matchYears(String original){
        List<Integer> found = new ArrayList<>();
        Matcher compact = QUARTER_COMPACT.matcher(original);
        while(compact.find()){
            add(found, expandYear(compact.group(2)));
        }
        Matcher half = HALF_YEAR.matcher(original);
        while (half.find()) {
            add(found, expandYear(half.group(2)));
        }
        if (!found.isEmpty()){
            return found;
        }
        Matcher year = YEAR.matcher(original);
        while(year.find()){
            add(found, Integer.valueOf(year.group()));
        }
        return found;
    }
    private Integer expandYear(String raw){
        int value = Integer.parseInt(raw);
        return raw.length() == 2 ? 2000 + value : value;
    }
    private List<String> matchScopes(String question){
        List<String> found = new ArrayList<>();
        for (Map.Entry<Pattern, String> entry : SCOPE_KEYWORDS) {
            if (entry.getKey().matcher(question).find()){
                add(found, entry.getValue());
            }
        }
        return found;
    }
    private static <T> void add(List<T> list, T value){
        if (value != null && !list.contains(value)){
            list.add(value);
        }
    }
    private String normalize(String text){
        String decomposed = Normalizer.normalize(text, Normalizer.Form.NFD);
        return decomposed.replaceAll("\\p{M}+", "").toLowerCase(Locale.ROOT);
    }
}
