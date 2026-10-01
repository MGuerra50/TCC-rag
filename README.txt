Pré-requisitos: Docker no WSL, Java 25, e chave API Gemini.

Iniciar (banco de dados vazio):
1. Preencher GEMINI_API_KEY no arquivo .env dentro da pasta rag-ingestion
2. Se não houver, colocar PDFs (relatórios de RI de empresas) com OCR em uma pasta "data" (na raiz do projeto)
3. No WSL rodar "cd rag-ingestion", em seguida rodar "docker compose up --build"
4. Aguardar a mensagem "Ingestion finished"

Iniciar (banco de dados já preenchido):
1. No WSL rodar "cd rag-ingestion", em seguida rodar "docker compose up -d db"
2. Após o banco de dados já estar rodando, é necessário configurar no windows a variável de ambiente do Gemini, se ainda não foi configurada:
    - Pode ser feito manualmente no Windows em Propriedades do Sistema > Variáveis de ambiente
    - Pode ser feito pelo PowerShell com $env:GeminiAPIKeyRAG="sua_chave_da_api_aqui"
3. No PowerShell rodar "cd rag-backend/rag-backend", em seguida rodar ".\mvnw spring-boot:run" ou ".\mvnw.cmd spring-boot:run"
4. A API ficará disponível em http://localhost:8080