from typing import List

import numpy as np
from langchain_community.embeddings import DashScopeEmbeddings

# 向量模型归一化
class NormalizeDashScopeEmbeddings(DashScopeEmbeddings):
    def _12_normalize(self,vecs):
        v = np.asarray(vecs,dtype=np.float32)
        norms = np.linalg.norm(v,axis=1,keepdims=True)
        norms = np.where(norms == 0,1.0,norms)

        return (v/norms).tolist()

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        raw = super().embed_documents(texts)
        return self._12_normalize(raw)

    def embed_query(self, text: str) -> List[float]:
        raw = super().embed_query(text)
        normalized = self._12_normalize([raw])

        return normalized[0]