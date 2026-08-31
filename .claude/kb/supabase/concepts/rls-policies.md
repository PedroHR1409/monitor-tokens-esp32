# RLS Policies

> **Purpose**: Row-Level Security in Supabase -- policy types, auth helpers, multi-tenant patterns, and pitfalls
> **Confidence**: 0.95
> **MCP Validated**: 2026-04-14

## Overview

Row-Level Security (RLS) is a PostgreSQL feature that restricts which rows a query can access or modify, evaluated per-row at the database engine level. Supabase relies on RLS as the primary authorization mechanism: the `anon` and `authenticated` roles have no privileges by default, and RLS policies define exactly what each role can see and do. Tables without RLS enabled (and no restrictive grants) are publicly accessible to any role — a common cause of data exposure.

## The Concept

```sql
-- Step 1: Enable RLS on every table that holds user or tenant data
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.items    ENABLE ROW LEVEL SECURITY;

-- Step 2: Grant usage on the schema to Supabase roles
GRANT USAGE ON SCHEMA public TO anon, authenticated;

-- ─── auth.uid() Patterns ──────────────────────────────────────────────────

-- Users can read only their own profile
CREATE POLICY "users: select own"
  ON public.profiles
  FOR SELECT
  TO authenticated
  USING (auth.uid() = id);

-- Users can update their own profile
CREATE POLICY "users: update own"
  ON public.profiles
  FOR UPDATE
  TO authenticated
  USING (auth.uid() = id)
  WITH CHECK (auth.uid() = id);

-- Users can insert only rows where they are the owner
CREATE POLICY "items: insert own"
  ON public.items
  FOR INSERT
  TO authenticated
  WITH CHECK (auth.uid() = user_id);

-- ─── auth.jwt() Patterns ──────────────────────────────────────────────────

-- Read a custom claim added by an Auth Hook (e.g., org_id)
-- Requires a Custom Access Token Hook that injects org_id into app_metadata
CREATE POLICY "tenant: select own org"
  ON public.orders
  FOR SELECT
  TO authenticated
  USING (
    org_id = (auth.jwt() -> 'app_metadata' ->> 'org_id')::uuid
  );

-- Role-based access: only admins can delete
CREATE POLICY "admin: delete"
  ON public.items
  FOR DELETE
  TO authenticated
  USING (
    (auth.jwt() -> 'app_metadata' ->> 'role') = 'admin'
  );

-- ─── current_setting() Pattern ────────────────────────────────────────────

-- Useful for server-side impersonation or service-role operations
-- Set before running queries in a transaction
SET LOCAL "app.user_id" = '<uuid>';

CREATE POLICY "service: impersonate"
  ON public.items
  FOR SELECT
  USING (user_id = current_setting('app.user_id')::uuid);
```

## Quick Reference

| Function | Returns | Safe for RLS? |
|----------|---------|---------------|
| `auth.uid()` | `uuid` of current user | Yes |
| `auth.jwt()` | Full JWT as `jsonb` | Yes (read `app_metadata` only) |
| `auth.jwt() ->> 'sub'` | User ID as `text` | Yes (same as `auth.uid()::text`) |
| `auth.jwt() -> 'user_metadata'` | User-editable claims | No — users can set these |
| `auth.jwt() -> 'app_metadata'` | Service-role-editable claims | Yes — set via Auth Hooks only |
| `current_setting('app.x')` | Custom GUC value | Yes, for server-side patterns |

## Common Mistakes

### Wrong

```sql
-- Relying on user_metadata for authorization
CREATE POLICY "bad: user_metadata role check"
  ON public.items FOR DELETE
  USING ((auth.jwt() -> 'user_metadata' ->> 'role') = 'admin');
-- DANGER: any authenticated user can set their own user_metadata
-- via supabase.auth.updateUser({ data: { role: 'admin' } })
```

### Correct

```sql
-- Use app_metadata (only writable by service role / Auth Hook)
CREATE POLICY "good: app_metadata role check"
  ON public.items FOR DELETE
  TO authenticated
  USING ((auth.jwt() -> 'app_metadata' ->> 'role') = 'admin');

-- Or store roles in a separate table and join
CREATE POLICY "good: roles table"
  ON public.items FOR DELETE
  TO authenticated
  USING (
    EXISTS (
      SELECT 1 FROM public.user_roles
      WHERE user_id = auth.uid() AND role = 'admin'
    )
  );
```

## Related

- [Multi-Tenant RLS Pattern](../patterns/multi-tenant-rls.md)
- [pgvector Fundamentals](../concepts/pgvector-fundamentals.md)
