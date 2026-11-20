"""模型版本集中声明。

统一在此处维护，providers / initRag / Langfuse Trace 元数据都从这里取，
换模型时不会出现“代码换了、审计记录没换”的情况。
"""

CHAT_MODEL = "deepseek-v4.1-flash-1017"
REWRITE_MODEL = "deepseek-v4.1-flash-1017"
EMBEDDING_MODEL = "text-embedding-v1"
RERANKER_MODEL = "bge-reranker-v2-m3"
