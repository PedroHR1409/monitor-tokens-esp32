# Edge Functions

> **Purpose**: Supabase Edge Functions -- Deno runtime, CORS, client initialization, secrets, and local testing
> **Confidence**: 0.95
> **MCP Validated**: 2026-04-14

## Overview

Supabase Edge Functions are TypeScript functions that run on the Deno runtime, deployed globally at the edge. They are the escape hatch for logic that cannot live in the database: webhook receivers, third-party API proxies, custom auth flows, and compute-heavy operations. Every function is a single TypeScript file under `supabase/functions/{name}/index.ts`.

## The Concept

```typescript
// supabase/functions/my-function/index.ts
import { createClient } from "jsr:@supabase/supabase-js@2";

// CORS headers required for browser clients
const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
};

Deno.serve(async (req: Request) => {
  // Handle CORS preflight — must return 200 for OPTIONS
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  try {
    // Initialize Supabase client with the request's Authorization header
    // This preserves the calling user's auth context + RLS enforcement
    const supabase = createClient(
      Deno.env.get("SUPABASE_URL")!,
      Deno.env.get("SUPABASE_ANON_KEY")!,
      {
        global: {
          headers: { Authorization: req.headers.get("Authorization")! },
        },
      }
    );

    // Access custom secrets set via `supabase secrets set MY_API_KEY=...`
    const apiKey = Deno.env.get("MY_API_KEY");
    if (!apiKey) throw new Error("MY_API_KEY not configured");

    const { data, error } = await req.json();
    if (error) throw error;

    // Perform DB operation — respects RLS because we forwarded the JWT
    const { data: result, error: dbError } = await supabase
      .from("events")
      .insert({ payload: data })
      .select()
      .single();

    if (dbError) throw dbError;

    return new Response(JSON.stringify({ id: result.id }), {
      headers: { ...corsHeaders, "Content-Type": "application/json" },
      status: 200,
    });
  } catch (err) {
    return new Response(JSON.stringify({ error: (err as Error).message }), {
      headers: { ...corsHeaders, "Content-Type": "application/json" },
      status: 400,
    });
  }
});
```

## Quick Reference

| Topic | Detail |
|-------|--------|
| Runtime | Deno 1.x (no Node.js APIs) |
| Import maps | `jsr:` (JSR registry) or `npm:` prefix |
| Supabase JS | `jsr:@supabase/supabase-js@2` |
| Auto env vars | `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` |
| Custom secrets | `supabase secrets set KEY=value` → `Deno.env.get("KEY")` |
| Local secrets file | `supabase/functions/.env` (auto-loaded by `supabase start`) |
| Local test command | `supabase functions serve my-function --env-file .env.local` |
| Deploy command | `supabase functions deploy my-function` |

## Common Mistakes

### Wrong

```typescript
// Using service role key with the user's request — bypasses RLS
const supabase = createClient(url, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
// The service role bypasses ALL RLS policies.
// Only use service role for trusted backend operations.

// Hardcoding a secret
const stripeKey = "sk_live_abc123...";
```

### Correct

```typescript
// Forward the user JWT for RLS-aware client
const supabase = createClient(url, anonKey, {
  global: { headers: { Authorization: req.headers.get("Authorization")! } },
});

// Use service role only for privileged operations in a separate client
const adminSupabase = createClient(url, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);

// Always load secrets from environment
const stripeKey = Deno.env.get("STRIPE_SECRET_KEY")!;
```

## Related

- [Webhook Edge Function Pattern](../patterns/webhook-edge-function.md)
- [RLS Policies](../concepts/rls-policies.md)
