"""TF-IDF runbook retrieval (lineage: Project 6, agentic RAG).

Project 6 retrieved facts with TF-IDF plus a topic boost. That retriever is kept
(Lewis et al., 2020 describe the retrieve-then-generate pattern) and extended
with bigrams, a 29-entry corpus of verbatim kubernetes.io excerpts (CC BY 4.0)
and citation metadata (runbook id + source URL) on every hit.
"""
from __future__ import annotations

from functools import lru_cache

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .data_utils import load_runbooks

TOPIC_BOOST = 0.15
MIN_SCORE = 0.05


class RunbookIndex:
    def __init__(self):
        self.df = load_runbooks()
        corpus = (self.df["title"] + ". " + self.df["topic"] + ". " + self.df["content"]).tolist()
        self.vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
        self.matrix = self.vec.fit_transform(corpus)

    def search(self, query: str, k: int = 3) -> list[dict]:
        q = self.vec.transform([query])
        scores = cosine_similarity(q, self.matrix).ravel()
        ql = query.lower().replace(" ", "")
        for i, topic in enumerate(self.df["topic"]):
            if topic.replace("-", "") in ql.replace("-", ""):
                scores[i] += TOPIC_BOOST
        order = scores.argsort()[::-1][:k]
        out = []
        for i in order:
            if scores[i] < MIN_SCORE:
                continue
            r = self.df.iloc[i]
            out.append({"id": r["id"], "title": r["title"], "topic": r["topic"],
                        "content": r["content"], "source": r["source"],
                        "kubesentinel_policy": r["kubesentinel_policy"] if isinstance(r["kubesentinel_policy"], str) else "",
                        "score": round(float(scores[i]), 3)})
        return out


@lru_cache(maxsize=1)
def get_index() -> RunbookIndex:
    return RunbookIndex()
