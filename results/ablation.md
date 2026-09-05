# Retrieval ablation — BM25 vs dense vs hybrid

Corpus: 12 heading-chunked passages. Gold = one passage per query. Dense = BAAI/bge-small-en-v1.5 + FAISS inner product; hybrid = reciprocal-rank fusion (c=60).

### structured (graph queries) — n=6

| Ranker | R@1 | R@3 | MRR |
|---|---|---|---|
| BM25 | 1.00 | 1.00 | 1.00 |
| dense (bge-small) | 1.00 | 1.00 | 1.00 |
| hybrid RRF | 1.00 | 1.00 | 1.00 |

### natural-language (analyst queries) — n=12

| Ranker | R@1 | R@3 | MRR |
|---|---|---|---|
| BM25 | 0.58 | 0.67 | 0.69 |
| dense (bge-small) | 0.75 | 0.92 | 0.85 |
| hybrid RRF | 0.75 | 0.92 | 0.83 |

### all — n=18

| Ranker | R@1 | R@3 | MRR |
|---|---|---|---|
| BM25 | 0.72 | 0.78 | 0.79 |
| dense (bge-small) | 0.83 | 0.94 | 0.90 |
| hybrid RRF | 0.83 | 0.94 | 0.89 |
