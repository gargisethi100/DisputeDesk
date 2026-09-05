"""dense.py — optional dense retrieval (bge-small + FAISS). Ported from ClauseLens.

Off by default. `Retriever` imports this only when DISPUTEDESK_DENSE_RETRIEVAL=1 and
degrades to BM25 if the import fails. bge wants an instruction prefix on QUERIES only;
passages are encoded bare. Vectors are L2-normalised so inner product == cosine.
"""
from __future__ import annotations

try:                                    # HF model download through a corporate proxy
    import truststore
    truststore.inject_into_ssl()
except Exception:                       # pragma: no cover
    pass

from .models import Passage

BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
MODEL_ID = "BAAI/bge-small-en-v1.5"


class DenseIndex:
    def __init__(self, passages: list[Passage], model_id: str = MODEL_ID) -> None:
        import faiss
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_id)
        vecs = self.model.encode([p.heading + "\n" + p.text for p in passages], normalize_embeddings=True,
                                 convert_to_numpy=True, show_progress_bar=False).astype("float32")
        self.index = faiss.IndexFlatIP(vecs.shape[1])
        self.index.add(vecs)
        self.n = len(passages)

    def rank(self, query: str) -> list[int]:
        q = self.model.encode([BGE_QUERY_PREFIX + query], normalize_embeddings=True,
                              convert_to_numpy=True, show_progress_bar=False).astype("float32")
        _, idx = self.index.search(q, self.n)
        return [int(i) for i in idx[0] if i >= 0]
