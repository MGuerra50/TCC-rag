from __future__ import annotations
from google.api_core import exceptions as google_exceptions
import src.main
from src.gemini_client import(
    EMBEDDING_TIMEOUT,
    MAX_DEADLINE_RETRIES,
    EmbeddingBatchLargeError,
    GeminiEmbeddingClient,
    _resumo,
)
falhas=0

def checa(rotulo:str, condicao:bool, detalhe:str="")->None:
    global falhas
    if not condicao:
        falhas+=1
    print(f"{'OK ' if condicao else 'FALHA'} {rotulo}")
    if detalhe:
        print(f" {detalhe}")

raiz= RuntimeError("DEADLINE_EXCEEDED:Dealine Exceeded")
meio=google_exceptions.DeadlineExceeded("504 Deadline Exceeded")
meio.__cause__=raiz
topo=Exception("Erro transitório de embedding após 7 tentativas: 504 Deadline Exceeded")
topo.__cause__=meio
resumo=_resumo(topo)
checa("resumo cabe em uma linha", "\n" not in resumo, resumo)
checa("resumo preserva a causa raiz", "DeadlineExceeded" in resumo)
checa("resumo nao vira uma parede", len(resumo) < 500, f"{len(resumo)} caracteres")
print()
print(f"EMBEDDING_TIMEOUT={EMBEDDING_TIMEOUT}s MAX_DEADLINE_RETRIES={MAX_DEADLINE_RETRIES}")

class ClienteFalso(GeminiEmbeddingClient):
    def __init__(self)->None:
        self.min_batch=20
        self.chamadas=0

    def _embed_batch_once(self, texts):
        self.chamadas+=1
        raise google_exceptions.DeadlineExceeded("504 Deadline Exceeded")

    def _wait_for_slot(self, n):
        pass

import time as _time
_time.sleep=lambda *_a, **_k:None
cliente=ClienteFalso()
try:
    cliente._embed_batch_with_retries(["texto"] * 40)
    checa("lote grande com 504 repetido vira EmbeddingBatchTooLargeError", False)
except EmbeddingBatchTooLargeError as exc:
    checa("lote grande com 504 repetido vira EmbeddingBatchTooLargeError", True, str(exc))
    checa(
        f"desistiu do tamanho em {MAX_DEADLINE_RETRIES} tentativas, nao em 7",
        cliente.chamadas <= MAX_DEADLINE_RETRIES,
        f"{cliente.chamadas} chamada(s)",
    )
except Exception as exc:
    checa("lote grande com 504 repetido vira EmbeddingBatchTooLargeError", False, repr(exc))
piso=ClienteFalso()
try:
    piso._embed_batch_with_retries(["texto"] * 20)
    checa("no lote minimo NAO tenta encolhe", False)
except EmbeddingBatchLargeError:
    checa("no lote minimo NAO tenta encolher", False, "encolheu abaixo do piso")
except Exception:
    checa("no lote minimo NAO tenta encolher", True, f"{piso.chamadas} tentativas transitorias")

print()
print("TODOS OS TESTES PASSARAM" if falhas == 0 else f"{falhas} FALHA(S))")
raise SystemExit(1 if falhas else 0)