# RAG Vector Store Pattern

> **Purpose**: End-to-end RAG pattern using Supabase pgvector -- table setup, HNSW index, match function, metadata filtering, and query
> **MCP Validated**: 2026-04-14

## When to Use

- Building a semantic search or question-answering system backed by a Postgres database
- You already use Supabase and want to avoid a separate vector database
- You need metadata filtering alongside vector similarity (e.g., filter by org, date range, document type)
- You want RLS to control which documents each user can retrieve

## Implementation

```sql
-- ─── 1. Schema ────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE public.documents (
  id          bigserial PRIMARY KEY,
  org_id      uuid         NOT NULL,           -- tenant isolation
  title       text,
  content     text         NOT NULL,
  metadata    jsonb        DEFAULT '{}'::jsonb, -- chunk_index, source_url, etc.
  embedding   vector(1536) NOT NULL,
  created_at  timestamptz  DEFAULT now()
);

-- ─── 2. HNSW Index ────────────────────────────────────────────────────────
CREATE INDEX documents_embedding_hnsw
  ON public.documents
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 128);

-- Index on metadata for JSONB filter performance
CREATE INDEX documents_metadata_gin ON public.documents USING gin (metadata);

-- ─── 3. Enable RLS ────────────────────────────────────────────────────────
ALTER TABLE public.documents ENABLE ROW LEVEL SECURITY;

CREATE POLICY "documents: org members can select"
  ON public.documents FOR SELECT
  TO authenticated
  USING (
    org_id = (auth.jwt() -> 'app_metadata' ->> 'org_id')::uuid
  );

-- ─── 4. Match Function ────────────────────────────────────────────────────
-- PostgREST cannot pass vector literals via REST, so wrap in an RPC function.
CREATE OR REPLACE FUNCTION match_documents(
  query_embedding  vector(1536),
  match_threshold  float   DEFAULT 0.75,
  match_count      int     DEFAULT 5,
  filter           jsonb   DEFAULT '{}'::jsonb
)
RETURNS TABLE (
  id          bigint,
  title       text,
  content     text,
  metadata    jsonb,
  similarity  float
)
LANGUAGE plpgsql
SECURITY INVOKER   -- run as calling user, so RLS applies
AS $$
BEGIN
  RETURN QUERY
  SELECT
    d.id,
    d.title,
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

```typescript
// ─── 5. Ingest (TypeScript / Node) ───────────────────────────────────────
import { createClient } from "@supabase/supabase-js";
import OpenAI from "openai";

const supabase = createClient(process.env.SUPABASE_URL!, process.env.SUPABASE_SERVICE_ROLE_KEY!);
const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY! });

async function ingestDocument(
  orgId: string,
  title: string,
  chunks: string[],
  sourceUrl: string
) {
  const embeddings = await openai.embeddings.create({
    model: "text-embedding-3-small",
    input: chunks,
  });

  const rows = chunks.map((content, i) => ({
    org_id: orgId,
    title,
    content,
    metadata: { chunk_index: i, source_url: sourceUrl },
    embedding: embeddings.data[i].embedding,
  }));

  const { error } = await supabase.from("documents").insert(rows);
  if (error) throw error;
}

// ─── 6. Query ─────────────────────────────────────────────────────────────
async function semanticSearch(
  userSupabase: ReturnType<typeof createClient>,
  query: string,
  filter?: Record<string, unknown>
) {
  // Embed the user's question
  const { data } = await openai.embeddings.create({
    model: "text-embedding-3-small",
    input: query,
  });

  const { data: results, error } = await userSupabase.rpc("match_documents", {
    query_embedding: data[0].embedding,
    match_threshold: 0.75,
    match_count: 5,
    filter: filter ?? {},
  });

  if (error) throw error;
  return results; // [{ id, title, content, metadata, similarity }]
}
```

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `match_threshold` | `0.75` | Minimum cosine similarity (0-1). Lower = more results, less precise |
| `match_count` | `5` | Maximum number of results returned |
| `m` (HNSW) | `16` | Connections per layer; increase to 32 for higher recall |
| `ef_construction` | `128` | Build-time search width; higher = better recall, slower build |
| `vector(1536)` | - | Match embedding model dimensions exactly |

## Example Usage

```typescript
// With metadata filter — only documents tagged as "policy" type
const results = await semanticSearch(
  supabase,
  "What is the refund policy?",
  { doc_type: "policy" }
);

// Stream results to an LLM for generation
const context = results.map((r) => r.content).join("\n\n");
const completion = await openai.chat.completions.create({
  model: "gpt-4o",
  messages: [
    { role: "system", content: `Answer using this context:\n${context}` },
    { role: "user", content: "What is the refund policy?" },
  ],
});
```

## See Also

- [pgvector Fundamentals](../concepts/pgvector-fundamentals.md)
- [RLS Policies](../concepts/rls-policies.md)
- [Multi-Tenant RLS](../patterns/multi-tenant-rls.md)
