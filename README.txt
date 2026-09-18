Pré-requisitos: Docker no WSL, Java 25, e chave API Gemini.

Iniciar (banco de dados vazio):
1. Preencher GEMINI_API_KEY no arquivo .env dentro da pasta rag-ingestion
2. Se não houver, colocar PDFs (relatórios de RI de empresas) com OCR em uma pasta "data" (na raiz do projeto)
3. No WSL rodar "cd rag-ingestion", em seguida rodar "docker compose up --build"
4. Aguardar a mensagem "Ingestion finished"

Iniciar (banco de dados já preenchido):
1. No WSL rodar "cd rag-ingestion", em seguida rodar "docker compose up -d db"