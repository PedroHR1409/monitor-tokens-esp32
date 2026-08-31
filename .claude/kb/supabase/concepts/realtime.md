# Realtime

> **Purpose**: Supabase Realtime -- Broadcast, Presence, and Postgres Changes channels with RLS interaction
> **Confidence**: 0.95
> **MCP Validated**: 2026-04-14

## Overview

Supabase Realtime is a WebSocket-based system providing three channel types: Broadcast for low-latency ephemeral messages, Presence for shared in-memory state (e.g., online users), and Postgres Changes for streaming database mutations to clients. All three operate through named channels and integrate with Supabase Auth for access control.

## The Concept

```typescript
import { createClient } from "@supabase/supabase-js";

const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

// ─── Broadcast ────────────────────────────────────────────────────────────
// Low-latency ephemeral pub/sub. Messages are NOT stored in the database.
const broadcastChannel = supabase.channel("room:lobby");

broadcastChannel
  .on("broadcast", { event: "cursor-move" }, (payload) => {
    console.log("cursor position:", payload);
  })
  .subscribe();

// Send a broadcast message
await broadcastChannel.send({
  type: "broadcast",
  event: "cursor-move",
  payload: { x: 100, y: 200, userId: "abc" },
});

// ─── Presence ─────────────────────────────────────────────────────────────
// In-memory key-value store using CRDTs. Shows who is online in a channel.
const presenceChannel = supabase.channel("room:online-users");

presenceChannel
  .on("presence", { event: "sync" }, () => {
    const state = presenceChannel.presenceState();
    console.log("online users:", state);
  })
  .on("presence", { event: "join" }, ({ newPresences }) => {
    console.log("joined:", newPresences);
  })
  .on("presence", { event: "leave" }, ({ leftPresences }) => {
    console.log("left:", leftPresences);
  })
  .subscribe(async (status) => {
    if (status === "SUBSCRIBED") {
      // Track current user's presence
      await presenceChannel.track({ userId: "user-123", online_at: new Date().toISOString() });
    }
  });

// ─── Postgres Changes ─────────────────────────────────────────────────────
// Listen for INSERT, UPDATE, DELETE, or * on a table.
// Requires the table to be added to the Realtime publication.
const changesChannel = supabase
  .channel("db-changes")
  .on(
    "postgres_changes",
    {
      event: "INSERT",
      schema: "public",
      table: "messages",
      // Optional: filter to specific rows using Postgres filter syntax
      filter: "room_id=eq.lobby-room",
    },
    (payload) => {
      console.log("new message:", payload.new);
    }
  )
  .subscribe();

// Cleanup on component unmount / disconnect
supabase.removeChannel(broadcastChannel);
supabase.removeChannel(presenceChannel);
supabase.removeChannel(changesChannel);
```

## Quick Reference

| Channel Type | Use Case | Persistence | Max Payload |
|--------------|----------|-------------|-------------|
| Broadcast | Cursor positions, typing indicators, ephemeral events | None (in-memory) | 1 MB |
| Presence | Online user lists, document co-editors, lobby state | In-memory (CRDT) | 1 MB per user key |
| Postgres Changes | Order status updates, chat messages, notifications | Database (WAL) | Row size limit |

## Common Mistakes

### Wrong

```typescript
// Subscribing to Postgres Changes without enabling the publication
// If the table is not in supabase_realtime publication, no events fire
channel.on("postgres_changes", { event: "*", schema: "public", table: "orders" }, cb);
// Also: Postgres Changes does NOT enforce RLS on the payload delivered.
// A user subscribed to the channel receives all matching rows.
```

### Correct

```typescript
// Enable the table in Realtime via SQL or Dashboard
-- SQL: add table to the publication
ALTER PUBLICATION supabase_realtime ADD TABLE public.messages;

// Use channel-level JWT authorization (Broadcast/Presence) or
// filter sensitive data in the application layer before sending.
// For Postgres Changes, always filter by user-owned rows using
// the `filter` option so clients only receive their own data:
channel.on("postgres_changes", {
  event: "INSERT",
  schema: "public",
  table: "notifications",
  filter: `user_id=eq.${userId}`,
}, cb);
```

## Related

- [RLS Policies](../concepts/rls-policies.md)
- [Edge Functions](../concepts/edge-functions.md)
