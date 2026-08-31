# pgvector Fundamentals

> **Purpose**: Vector storage and similarity search in Supabase using the pgvector PostgreSQL extension
> **Confidence**: 0.95
> **MCP Validated**: 2026-04-14

## Overview

pgvector is a PostgreSQL extension that adds vector column types, distance operators, and approximate nearest-neighbor (ANN) indexes. Supabase ships pgvector pre-installed on all projects, making it the default choice for embedding storage and semantic search without a separate vector database.

## The Concept

```sql
-- 1. Enable the extension (already enabled on Supabase by default)
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Create a table with an embedding column
--    1536 = OpenAI text-embedding-3-small dimensions
--    3072 = text-embedding-3-large / Gemini embedding-001
CREATE TABLE public.documents (
  id          bigserial PRIMARY KEY,
  content     text         NOT NULL,
  metadata    jsonb        DEFAULT '{}'::jsonb,
  embedding   vector(1536) NOT NULL
);

-- 3. Create an HNSW index (recommended for most workloads)
--    m           = max connections per layer (default 16)
--    ef_construction = build-time search width (default 64, higher = better recall)
CREATE INDEX ON public.documents
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 128);

-- 4. Create a match function for RPC-based similarity search
CREATE OR REPLACE FUNCTION match_documents(
  query_embedding vector(1536),
  match_threshold float  DEFAULT 0.75,
  match_count     int    DEFAULT 5,
  filter          jsonb  DEFAULT '{}'::jsonb
)
RETURNS TABLE (
  id         bigint,
  content    text,
  metadata   jsonb,
  similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    d.id,
    d.content,
    d.metadata,
    1 - (d.embedding <=> query_embedding) AS similarity
  FROM public.documents d
  WHERE
    d.metadata @> filter
    AND 1 - (d.embedding <=> query_embedding) > match_threshold
  ORDER BY d.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;
```

## Quick Reference

| Input | Output | Notes |
|-------|--------|-------|
| `vector_cosine_ops` | Cosine similarity | Best for text; normalized embeddings |
| `vector_l2_ops` | L2 distance | Image/audio; euclidean space |
| `vector_ip_ops` | Inner product | When all vectors are unit-normalized |
| `1 - (a <=> b)` | Similarity score 0-1 | Invert distance to get similarity |
| HNSW `m=16` | Good default | Increase to 32-64 for higher recall |
| HNSW `ef_construction=128` | Higher recall | Default is 64; more build time |

## Common Mistakes

### Wrong

```sql
-- Creating IVFFlat on an empty table
CREATE INDEX ON documents USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);
-- IVFFlat clusters are built at index creation time.
-- Empty table = useless clusters = poor recall.

-- Missing threshold check — returns all rows sorted by distance
SELECT * FROM documents
ORDER BY embedding <=> query_embedding
LIMIT 5;
-- This works but does not filter low-similarity results.
```

### Correct

```sql
-- Populate table first, then create IVFFlat
INSERT INTO documents (content, embedding) SELECT ...;
-- Aim for lists ≈ sqrt(row_count)
CREATE INDEX ON documents USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

-- Wrap in a function and use threshold
-- Use match_documents() RPC shown above — PostgREST cannot
-- pass vector literals directly via the REST API.
SELECT * FROM match_documents(
  query_embedding := '[0.1, 0.2, ...]'::vector,
  match_threshold := 0.75,
  match_count := 5
);
```

## Related

- [RAG Vector Store Pattern](../patterns/rag-vector-store.md)
- [RLS Policies](../concepts/rls-policies.md)
