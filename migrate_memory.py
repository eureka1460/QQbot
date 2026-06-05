"""Migrate group memory to per-user collections.

Usage: python migrate_memory.py [memory_db_path]
"""
import sys
import chromadb


def migrate(db_path: str = "./memory_db"):
    client = chromadb.PersistentClient(path=db_path)
    collections = client.list_collections()

    group_cols = [c for c in collections if c.name.startswith("group_")]
    print(f"Found {len(group_cols)} group collections")

    total_migrated = 0
    for col in group_cols:
        group_id = col.name.replace("group_", "")
        all_data = col.get(include=["embeddings", "documents", "metadatas"])
        if not all_data["ids"]:
            continue

        has_embeddings = all_data.get("embeddings") is not None and len(all_data["embeddings"]) > 0

        from collections import defaultdict
        user_batches = defaultdict(
            lambda: {"ids": [], "embeddings": [], "documents": [], "metadatas": []}
        )

        for i, doc_id in enumerate(all_data["ids"]):
            meta = all_data["metadatas"][i] if all_data.get("metadatas") else {}
            uid = meta.get("user_id", "")
            if not uid:
                continue
            user_batches[uid]["ids"].append(doc_id)
            if has_embeddings:
                user_batches[uid]["embeddings"].append(all_data["embeddings"][i])
            user_batches[uid]["documents"].append(all_data["documents"][i])
            user_batches[uid]["metadatas"].append(meta)

        for uid, batch in user_batches.items():
            user_col = client.get_or_create_collection(
                name=f"user_{uid}",
                metadata={"hnsw:space": "cosine"},
            )

            seen = set()
            dedup_ids, dedup_embs, dedup_docs, dedup_metas = [], [], [], []
            for j, idx in enumerate(batch["ids"]):
                if idx not in seen:
                    seen.add(idx)
                    dedup_ids.append(idx)
                    if has_embeddings:
                        dedup_embs.append(batch["embeddings"][j])
                    dedup_docs.append(batch["documents"][j])
                    dedup_metas.append(batch["metadatas"][j])

            user_col.upsert(
                ids=dedup_ids,
                embeddings=dedup_embs if dedup_embs else None,
                documents=dedup_docs,
                metadatas=dedup_metas,
            )
            print(f"  user_{uid}: upserted {len(dedup_ids)} messages (from group_{group_id})")
            total_migrated += len(dedup_ids)

    print(f"\nDone. Total messages migrated: {total_migrated}")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "./memory_db"
    migrate(path)
