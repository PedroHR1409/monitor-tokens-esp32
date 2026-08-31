# Supabase Quick Reference

> Fast lookup tables. For code examples, see linked files.
> **MCP Validated**: 2026-04-14

## Edge Function Limits

| Limit | Value | Notes |
|-------|-------|-------|
| Memory | 150 MB | Per invocation |
| CPU time | 400 ms | Wall-clock time is higher |
| Request body | 10 MB | Streaming not supported beyond this |
| Response size | No hard limit | Practical limit ~6 MB |
| Execution timeout | 150 s | Configurable per-function |
| Concurrent invocations | 200 (default) | Increase via dashboard |
| Regions | Global edge | Closest region auto-selected |

## pgvector Index Comparison

| Feature | HNSW | IVFFlat |
|---------|------|---------|
| Recall | High (95%+) | Medium (90%+) |
| Build time | Slower | Faster |
| Memory | Higher | Lower |
| Insert performance | Good (no rebuild needed) | Requires lists to be stable |
| Best for | Dynamic datasets, production | Static/batch datasets |
| Distance ops | `vector_cosine_ops`, `vector_l2_ops`, `vector_ip_ops` | Same |
| Recommended | Yes (default choice) | Low-memory constraint only |

## Distance Functions

| Operator | Function | Use Case |
|----------|----------|----------|
| `<=>` | Cosine distance | Text embeddings (most common) |
| `<->` | L2 (Euclidean) distance | Image/audio embeddings |
| `<#>` | Negative inner product | When vectors are normalized |

## RLS Policy Quick Patterns

```sql
-- Enable RLS on a table
ALTER TABLE public.table_name ENABLE ROW LEVEL SECURITY;

-- User can only see their own rows
CREATE POLICY "own rows" ON public.items
  FOR SELECT TO authenticated
  USING (auth.uid() = user_id);

-- Read JWT claim (custom field)
USING ((auth.jwt() ->> 'org_id') = org_id::text)

-- Service role bypasses RLS (be careful)
-- Use in migrations or backend-only operations
```

## Auth Configuration Cheat Sheet

| Setting | Location | Purpose |
|---------|----------|---------|
| JWT secret | Project Settings > API | Signing secret for tokens |
| Email templates | Auth > Email Templates | Customize confirmation/magic link emails |
| Site URL | Auth > URL Configuration | Allowed redirect URL |
| Additional redirect URLs | Auth > URL Configuration | Localhost, preview URLs |
| Custom SMTP | Auth > SMTP Settings | Production email delivery |
| Auth hook (custom claims) | Auth > Hooks | Inject custom JWT claims at login |

## Decision Matrix

| Use Case | Choose |
|----------|--------|
| Per-user data isolation | RLS with `auth.uid()` |
| Organization/tenant isolation | RLS with custom JWT claim via Auth Hook |
| Webhook receiver (Stripe, GitHub) | Edge Function with signature verification |
| Background job or cron | Edge Function + `pg_cron` or Supabase scheduled functions |
| Vector similarity search | pgvector with HNSW + `match_documents` RPC |
| Low-latency user presence | Realtime Presence channel |
| Database change event stream | Realtime Postgres Changes |
| Ephemeral pub/sub messages | Realtime Broadcast |
| API key / secret storage | Supabase Vault (`supabase_vault` extension) |

## Common Pitfalls

| Don't | Do |
|-------|-----|
| Leave RLS disabled on public tables | Always run `ALTER TABLE t ENABLE ROW LEVEL SECURITY` |
| Use `user_metadata` in RLS policies | Use `app_metadata` (only editable by service role) |
| Create IVFFlat index on empty table | Populate data first; IVFFlat clusters depend on distribution |
| Call `auth.uid()` on anon role without role check | Add `TO authenticated` to all non-public policies |
| Store secrets in Edge Function code | Use `Deno.env.get()` + `supabase secrets set` |
| Skip CORS preflight handling | Return 200 on OPTIONS with correct `Access-Control-*` headers |
| Use `raw_user_meta_data` for authorization | Use `raw_app_meta_data` or custom Auth Hook claims |
| Query vectors without an index | Create HNSW index before production load |

---

Full index: [`index.md`](index.md) | Concepts: `pgvector-fundamentals` · `rls-policies` · `edge-functions` · `realtime`
