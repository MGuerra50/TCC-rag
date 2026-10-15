package com.tcc.matheusguerra.rag_backend.model;
import java.util.UUID;
import com.fasterxml.jackson.annotation.JsonIgnore;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.NoArgsConstructor;
import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.Setter;

@Entity 
@Table(name="document_chunks_v2")
@Getter 
@Setter 
@NoArgsConstructor 
@AllArgsConstructor     
public class DocumentChunkV2 {
    @Id 
    private UUID id;
    @Column(columnDefinition = "TEXT")
    private String content;
    @Column(length = 255)
    private String company;
    private Integer year;
    @Column(length = 8)
    private String quarter;
    @Column(name="doc_type", length = 64)
    private String docType;
    @Column(name="page_number")
    private Integer pageNumber;
    @Column(name="source_path", columnDefinition = "TEXT")
    private String sourcePath;
    @Column(name="section_title", columnDefinition = "TEXT")
    private String sourceTitle;
    @Column(length = 64)
    private String scope;
    @Column(length = 16)
    private String scale;
    @Column(length = 8)
    private String currency;
    @Column(name="scale_source", length = 16)
    private String scaleSource;
    @Column(name="printed_page_label", length = 16)
    private String printedPageLabel;
    @Column(name="content_type", length = 16)
    private String contentType;
    @Column(name="context_header", columnDefinition = "TEXT")
    private String contextHeader;
    @Column(name="chunk_index")
    private Integer chunkIndex;
    @JsonIgnore 
    @Column(columnDefinition = "vector(768)")
    private String embedding;
}
