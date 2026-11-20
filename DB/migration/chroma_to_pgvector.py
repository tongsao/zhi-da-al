"""Chroma(data/vector_store) -> PostgreSQL pgvector 向量迁移。

用法（在项目根目录执行）：
    python DB/migration/chroma_to_pgvector.py            # 目标集合非空时拒绝执行
    python DB/migration/chroma_to_pgvector.py --force    # 清空目标集合后全量重导

说明：
- 直接搬运 Chroma 中已生成的向量，不重新调用 embedding 接口；
- 保留原向量 id 与全部元数据（fileid/filename/chunk_index/total_chunks/username）；
- 目标集合由 agent.rag.initRag 中的 PGVector 配置决定（zhida_embeddings）。
"""
import argparse
import sys
from pathlib import Path

import chromadb
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.rag.initRag import COLLECTION_NAME, EMBEDDING_DIM, getVector  # noqa: E402
from model.initDataBase import engine  # noqa: E402

CHROMA_DIR = Path("data/vector_store")


def count_target() -> int:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT COUNT(*) FROM langchain_pg_embedding e "
                "JOIN langchain_pg_collection c ON e.collection_id = c.uuid "
                "WHERE c.name = :name"
            ),
            {"name": COLLECTION_NAME},
        ).scalar()


def load_chroma() -> dict:
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = client.get_collection(COLLECTION_NAME)
    return collection.get(include=["embeddings", "documents", "metadatas"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="目标集合非空也执行（先清空）")
    args = parser.parse_args()

    data = load_chroma()
    ids = data["ids"]
    vectors = data["embeddings"]
    documents = data["documents"]
    metadatas = data["metadatas"]
    if hasattr(vectors, "tolist"):
        vectors = vectors.tolist()

    print(f"Chroma 向量 {len(ids)} 条，维度 {len(vectors[0]) if vectors else 0}")

    store = getVector()
    existing = count_target()
    if existing and not args.force:
        print(f"目标集合已有 {existing} 条向量，已中止（加 --force 清空后重导）")
        raise SystemExit(1)
    if existing:
        store.delete_collection()
        print(f"已清空目标集合（原 {existing} 条）")

    for start in range(0, len(ids), 100):
        end = start + 100
        store.add_embeddings(
            texts=documents[start:end],
            embeddings=vectors[start:end],
            metadatas=[m or {} for m in metadatas[start:end]],
            ids=ids[start:end],
        )
        print(f"  已写入 {min(end, len(ids))}/{len(ids)}")

    print(f"迁移完成，目标集合向量数: {count_target()}（期望 {len(ids)}，维度 {EMBEDDING_DIM}）")


if __name__ == "__main__":
    main()
