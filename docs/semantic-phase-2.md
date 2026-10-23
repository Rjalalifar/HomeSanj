# Semantic retrieval operations

The canonical implementation is `backend/app/semantic.py`; full deployment and state contracts
are in `handoff-phase-2.md`. SQLite remains authoritative. Normal search never calls this module's
encoder or Qdrant retrieval method.

- Collection: `homesanj_properties_v1`, cosine distance, 384 dimensions.
- Encoder: `Xenova/multilingual-e5-small`, revision `761b726dd34fb83930e26aab4e9ac3899aa1fa78`.
- Runtime: quantized ONNX on CPU, two threads by default, masked mean pooling, L2 normalization,
  maximum 192 tokens, E5 query/passsage prefixes. SHA256 hashes are checked before loading.
- Stable points: UUIDv5 of canonical property IDs. Payload includes dataset/model/description
  versions, factual descriptions, prices, area, bedrooms, tri-state amenities, district membership,
  source IDs, demo status and a content fingerprint.
- Shared indexing accepts synthetic listings or sources explicitly marked `public_listing=true`.
  User queries, private destinations and raw source text are excluded.
- Persistent Docker volume: `homesanj_qdrant_storage`; backend-only loopback port 6333.

```powershell
docker compose -f compose.qdrant.yml up -d
.\.venv\Scripts\python.exe -m backend.app.semantic download-model --report docs/embedding-verification.json
.\.venv\Scripts\python.exe -m backend.app.semantic index --report docs/qdrant-index-report.json
.\.venv\Scripts\python.exe -m backend.app.semantic reconcile --report docs/qdrant-reconcile-report.json
```

Indexing performs bounded idempotent batches and checks missing, changed and orphaned records.
Reindex after canonical facts, membership, model or description changes. Model/dimension/version
mismatch is an explicit degraded state; it never becomes a fabricated vector response. Imported
neighborhood IDs must come from the validated ingestion contract; district payloads use geometry.

Actual verification indexed all 5655 demo records and reported zero drift on reconciliation.
`advanced-semantic-live-report.json` retained all 707 exact-eligible candidates, recovered 100
semantic candidates and found zero hard-match violations. The hybrid policy uses reciprocal rank
fusion (k=60) over vector, lexical and exhaustive structured candidates to set routing priority;
semantic order only breaks deterministic utility ties. It cannot relax a hard constraint.

`semantic-benchmark.json` uses eight authored Persian fixture queries and eight synthetic listings.
It compares vector, FTS and hybrid Recall@K and measures warm retrieval latency. It is a small
engineering fixture, not a user study, a calibrated relevance probability or evidence of improved
production Hit Rate. The fixture collection is separate from the application collection.
