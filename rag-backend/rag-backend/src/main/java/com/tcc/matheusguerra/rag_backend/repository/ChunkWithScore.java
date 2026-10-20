package com.tcc.matheusguerra.rag_backend.repository;
import java.util.UUID;

public interface ChunkWithScore {
    UUID getId();
    String getContent();
    String getCompany();
    Integer getYear();
    String getQuarter();
    String getDocType();
    Integer getPageNumber();
    String getSourcePath();
    String getSectionTitle();
    String getScope();
    String getScale();
    String getScaleSource();
    String getCurrency();
    String getPrintedPageLabel();
    String getContentType();
    Integer getChunkIndex();
    Double getDistance();
    Double getScore();
}
