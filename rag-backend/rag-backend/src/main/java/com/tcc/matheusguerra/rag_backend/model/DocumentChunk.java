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
@Table(name = "document_chunks")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
public class DocumentChunk {
    @Id
    private UUID id;

    @Column(columnDefinition = "TEXT")
    private String content;

    @Column(length = 255)
    private String company;

    private Integer year;

    @Column(length = 8)
    private String quarter;

    @Column(name = "doc_type", length = 64)
    private String docType;

    @Column(name = "page_number")
    private Integer pageNumber;

    @Column(name = "source_path", columnDefinition = "TEXT")
    private String sourcePath;

    @JsonIgnore
    @Column(columnDefinition = "vector(768)")
    private String embedding;
}