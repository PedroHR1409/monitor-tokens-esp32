# Webhook Edge Function Pattern

> **Purpose**: Handle inbound webhooks (Stripe, GitHub, Clerk, etc.) in a Supabase Edge Function with signature verification and database writes
> **MCP Validated**: 2026-04-14

## When to Use

- Receiving payment events from Stripe (checkout.session.completed, invoice.paid)
- Processing GitHub webhook events (push, pull_request, deployment)
- Handling third-party auth events from Clerk or WorkOS
- Any case where an external service POSTs to a URL you control

## Implementation

```typescript
// supabase/functions/stripe-webhook/index.ts
import { createClient } from "jsr:@supabase/supabase-js@2";
import Stripe from "npm:stripe@14";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

// ─── Supabase admin client (service role bypasses RLS for webhook writes) ──
const supabase = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
);

const stripe = new Stripe(Deno.env.get("STRIPE_SECRET_KEY")!, {
  apiVersion: "2024-12-18.acacia",
  httpClient: Stripe.createFetchHttpClient(), // Deno-compatible HTTP client
});

const webhookSecret = Deno.env.get("STRIPE_WEBHOOK_SECRET")!;

Deno.serve(async (req: Request) => {
  // Handle CORS preflight
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  if (req.method !== "POST") {
    return new Response("Method Not Allowed", { status: 405 });
  }

  // ─── 1. Read raw body for signature verification ──────────────────────
  const rawBody = await req.text();
  const signature = req.headers.get("stripe-signature");

  if (!signature) {
    return new Response(JSON.stringify({ error: "Missing stripe-signature header" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  // ─── 2. Verify webhook signature ─────────────────────────────────────
  let event: Stripe.Event;
  try {
    event = await stripe.webhooks.constructEventAsync(rawBody, signature, webhookSecret);
  } catch (err) {
    console.error("Webhook signature verification failed:", err);
    return new Response(JSON.stringify({ error: "Invalid signature" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  // ─── 3. Idempotency check — skip already-processed events ────────────
  const { data: existing } = await supabase
    .from("webhook_events")
    .select("id")
    .eq("stripe_event_id", event.id)
    .single();

  if (existing) {
    // Return 200 to prevent Stripe from retrying
    return new Response(JSON.stringify({ received: true, duplicate: true }), {
      headers: { "Content-Type": "application/json" },
    });
  }

  // ─── 4. Process the event ─────────────────────────────────────────────
  try {
    switch (event.type) {
      case "checkout.session.completed": {
        const session = event.data.object as Stripe.Checkout.Session;
        await handleCheckoutCompleted(session);
        break;
      }
      case "invoice.payment_failed": {
        const invoice = event.data.object as Stripe.Invoice;
        await handlePaymentFailed(invoice);
        break;
      }
      default:
        console.log(`Unhandled event type: ${event.type}`);
    }

    // ─── 5. Record processed event for idempotency ────────────────────
    await supabase.from("webhook_events").insert({
      stripe_event_id: event.id,
      event_type: event.type,
      processed_at: new Date().toISOString(),
    });
  } catch (err) {
    console.error(`Error processing ${event.type}:`, err);
    // Return 500 so Stripe retries the event
    return new Response(JSON.stringify({ error: "Processing failed" }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }

  return new Response(JSON.stringify({ received: true }), {
    headers: { "Content-Type": "application/json" },
  });
});

// ─── Handler Functions ────────────────────────────────────────────────────
async function handleCheckoutCompleted(session: Stripe.Checkout.Session) {
  const { customer_email, metadata } = session;
  const orgId = metadata?.org_id;

  if (!orgId) throw new Error("Missing org_id in session metadata");

  const { error } = await supabase
    .from("subscriptions")
    .upsert({
      org_id: orgId,
      stripe_customer_id: session.customer as string,
      status: "active",
      plan: metadata?.plan ?? "starter",
      updated_at: new Date().toISOString(),
    }, { onConflict: "org_id" });

  if (error) throw error;
  console.log(`Subscription activated for org ${orgId} (${customer_email})`);
}

async function handlePaymentFailed(invoice: Stripe.Invoice) {
  const customerId = invoice.customer as string;

  const { error } = await supabase
    .from("subscriptions")
    .update({ status: "past_due", updated_at: new Date().toISOString() })
    .eq("stripe_customer_id", customerId);

  if (error) throw error;
}
```

## Configuration

| Setting | Secret Name | Description |
|---------|-------------|-------------|
| Stripe secret key | `STRIPE_SECRET_KEY` | `sk_live_...` or `sk_test_...` |
| Stripe webhook secret | `STRIPE_WEBHOOK_SECRET` | From Stripe dashboard webhook endpoint |
| Supabase service role | Auto-injected | Available as `SUPABASE_SERVICE_ROLE_KEY` |

```bash
# Register secrets before deploying
supabase secrets set STRIPE_SECRET_KEY=sk_live_...
supabase secrets set STRIPE_WEBHOOK_SECRET=whsec_...

# Test locally with Stripe CLI forwarding
stripe listen --forward-to http://localhost:54321/functions/v1/stripe-webhook
supabase functions serve stripe-webhook --env-file supabase/functions/.env.local
```

## Example Usage

```sql
-- webhook_events table for idempotency tracking
CREATE TABLE public.webhook_events (
  id               bigserial    PRIMARY KEY,
  stripe_event_id  text         UNIQUE NOT NULL,
  event_type       text         NOT NULL,
  processed_at     timestamptz  DEFAULT now()
);

-- Do not expose this table via RLS to authenticated users
ALTER TABLE public.webhook_events ENABLE ROW LEVEL SECURITY;
-- No SELECT/INSERT policies — only service role (used in Edge Function) can write
```

## See Also

- [Edge Functions Concept](../concepts/edge-functions.md)
- [Multi-Tenant RLS Pattern](../patterns/multi-tenant-rls.md)
