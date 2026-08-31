# Supabase Knowledge Base

> **Purpose**: Supabase development -- pgvector, RLS policies, Edge Functions, Auth, Realtime, database migrations
> **MCP Validated**: 2026-04-14

## Quick Navigation

### Concepts (< 150 lines each)

| File | Purpose |
|------|---------|
| [concepts/pgvector-fundamentals.md](concepts/pgvector-fundamentals.md) | pgvector extension, HNSW vs IVFFlat indexes, distance functions, match functions |
| [concepts/rls-policies.md](concepts/rls-policies.md) | Row-Level Security, auth.uid(), auth.jwt(), policy types, multi-tenant patterns |
| [concepts/edge-functions.md](concepts/edge-functions.md) | Deno Edge Functions, CORS, client initialization, secrets, local testing |
| [concepts/realtime.md](concepts/realtime.md) | Broadcast, Presence, Postgres Changes channels, RLS interaction |

### Patterns (< 200 lines each)

| File | Purpose |
|------|---------|
| [patterns/rag-vector-store.md](patterns/rag-vector-store.md) | Full RAG pattern: table → HNSW index → match function → query with metadata filtering |
| [patterns/multi-tenant-rls.md](patterns/multi-tenant-rls.md) | Organization-based access, custom JWT claims, role-based policies, isolation testing |
| [patterns/webhook-edge-function.md](patterns/webhook-edge-function.md) | Webhook handler, signature verification, DB writes from Edge Functions, error handling |

---

## Quick Reference

- [quick-reference.md](quick-reference.md) - Fast lookup tables and decision matrix

---

## Key Concepts

| Concept | Description |
|---------|-------------|
| **pgvector** | PostgreSQL extension enabling vector storage and similarity search (cosine, L2, inner product) |
| **RLS** | Row-Level Security enforces access at the database level using PostgreSQL policies |
| **auth.uid()** | Returns the UUID of the currently authenticated Supabase user |
| **auth.jwt()** | Returns the full JWT payload; use `auth.jwt() ->> 'claim'` to extract specific claims |
| **Edge Functions** | Server-side TypeScript functions running on Deno at the edge, globally distributed |
| **Realtime** | WebSocket-based system for Broadcast, Presence, and Postgres database change events |
| **HNSW** | Hierarchical Navigable Small World — default index for pgvector; high recall, fast query |
| **IVFFlat** | Inverted File Flat index — lower memory than HNSW; best for static datasets |

---

## Learning Path

| Level | Files |
|-------|-------|
| **Beginner** | concepts/rls-policies.md → concepts/pgvector-fundamentals.md |
| **Intermediate** | patterns/multi-tenant-rls.md → patterns/rag-vector-store.md |
| **Advanced** | concepts/edge-functions.md → patterns/webhook-edge-function.md |

---

## Agent Usage

| Agent | Primary Files | Use Case |
|-------|---------------|----------|
| supabase-specialist | All files | Full Supabase development -- auth, database, storage, functions |
| ai-data-engineer | concepts/pgvector-fundamentals.md, patterns/rag-vector-store.md | RAG pipelines backed by Supabase pgvector |
| data-quality-analyst | concepts/rls-policies.md | Verifying RLS policies cover all data access paths |
