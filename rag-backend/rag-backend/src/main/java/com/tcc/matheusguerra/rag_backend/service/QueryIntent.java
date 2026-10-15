package com.tcc.matheusguerra.rag_backend.service;
import java.util.ArrayList;
import java.util.List;

public record QueryIntent(
    List<String> companies,
    List<Integer> years,
    List<String> quarters,
    List<String> scopes,
    boolean periodWasInferred
) {
    public static final int MAX_VARIANTS=6;
    public QueryIntent {
        companies=List.copyOf(companies == null ? List.of() : companies);
        years=List.copyOf(years == null ? List.of() : years);
        quarters=List.copyOf(quarters == null ? List.of() : quarters);
        scopes=List.copyOf(scopes == null ? List.of() : scopes);
    }
    public static QueryIntent empty(){
        return new QueryIntent(List.of(), List.of(), List.of(),List.of(), false);
    }
    public QueryIntent withPeriod(Integer year, String quarter, boolean inferred){
        return new QueryIntent(
            companies,
            year==null ? List.of() : List.of(year), 
            quarter==null ? List.of() : List.of(quarter), 
            scopes, inferred);
    }
    public boolean hasPeriod(){
        return !years.isEmpty() || !quarters.isEmpty();
    }
    public String company(){
        return companies.isEmpty() ? null : companies.get(0);
    }
    public String periodLabel(){
        if (!hasPeriod()){
            return null;
        }
        List<String> partes = new ArrayList<>();
        for (Variant v : variants()){
            String p = v.label();
            if(p!=null&&!partes.contains(p)){
                partes.add(p);
            }
        }
        return partes.isEmpty() ? null : String.join(", ", partes);
    }
    public List<Variant> variants(){
        List<String> empresas = companies.isEmpty() ? nullList() : companies;
        List<Integer> anos = years.isEmpty() ? nullList() : years;
        List<String> tris = quarters.isEmpty() ? nullList() : quarters;
        List<String> escopos = scopes.isEmpty() ? nullList() : scopes;
        int porEmpresa = Math.max(1, MAX_VARIANTS / empresas.size());
        List<Variant> out = new ArrayList<>();
        for (String empresa: empresas){
            int usadas=0;
            cota:
            for (Integer ano: anos){
                for (String tri: tris){
                    for (String escopo: escopos){
                        if (usadas >= porEmpresa){
                            break cota;
                        }
                        out.add(new Variant(empresa, ano, tri, escopo));
                        usadas++;
                    }

                }
            }
        }
        return out;
    }
    private static <T> List<T> nullList(){
        List<T> l = new ArrayList<>();
        l.add(null);
        return l;
    }
    public record Variant(String company, Integer year, String quarter, String scope){
        public String label(){
            if (year == null && quarter == null){
                return null;
            }
            if (year == null){
                return quarter;
            }
            if (quarter == null) {
                return String.valueOf(year);                
            }
            return quarter+String.valueOf(year).substring(2);
        }
    }
}
