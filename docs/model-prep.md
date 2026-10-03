# Model prep (Ollama + BGE-M3)

v1 keeps the **LLM (Ollama)** and **embedding (BGE-M3)** services separate.

## Ollama (checklist `document_content` items)

Configured via `.env`:

| Variable | Role |
|---|---|
| `OLLAMA_BASE_URL` | Internal URL (`http://ollama:11434`) |
| `OLLAMA_LLM_MODEL` | Model tag (default example `qwen2.5:3b`) |
| `OLLAMA_MAX_CONCURRENCY` | **1** in v1 |

Pull a model **inside the Ollama container** on the deploy host after stack is up:

```bash
docker compose -p anova-checklist-review exec ollama ollama pull qwen2.5:3b
# or whatever OLLAMA_LLM_MODEL is set to
docker compose -p anova-checklist-review exec ollama ollama list
```

Notes:

- Do not share a host Ollama model store with other stacks by default (isolation).
- Verify VRAM/RAM on the host before choosing larger tags (7B+).
- Without a pulled model, deterministic / cross-doc / manual items still run; `document_content` items may ERROR.

## BGE-M3 embedding service

Configured via `.env`:

| Variable | Role |
|---|---|
| `EMBEDDING_URL` | `http://embedding:8080` |
| `EMBEDDING_MODEL_ID` | `BAAI/bge-m3` |
| `EMBEDDING_MODEL_REVISION` | Pin HF revision SHA when known |
| `EMBEDDING_DEVICE` | `cpu` default; `cuda` only if NVIDIA runtime confirmed |
| `EMBEDDING_LOAD_MODEL` | `0` = deterministic stub (default); `1` = real FlagEmbedding load |

### Stub mode (default)

No multi-GB download. Enough to exercise extract → index → search wiring in labs.

### Real model

1. Ensure embedding image has ML deps (`embedding/requirements-ml.txt` path as built).
2. Set `EMBEDDING_LOAD_MODEL=1` and adequate `EMBEDDING_MEM_LIMIT`.
3. Recreate embedding service; first start downloads weights (needs egress + disk).

```bash
# example
# EMBEDDING_LOAD_MODEL=1 in .env
docker compose -p anova-checklist-review up -d --build embedding
docker compose -p anova-checklist-review logs -f embedding
```

Do **not** publish the embedding port to the host.
