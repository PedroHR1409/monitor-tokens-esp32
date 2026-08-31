# Multi-Tenant RLS Pattern

> **Purpose**: Organization-based data isolation using RLS, custom JWT claims via Auth Hooks, and role-based access control
> **MCP Validated**: 2026-04-14

## When to Use

- SaaS applications where each organization should only access their own data
- Role-based access (admin, member, viewer) within a tenant
- You want authorization enforced at the database level, not just the API layer
- Third-party auth providers (Clerk, WorkOS) injecting custom claims into Supabase JWTs

## Implementation

```sql
-- ─── 1. Schema: org_id on every tenant-scoped table ──────────────────────
CREATE TABLE public.organizations (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name       text NOT NULL,
  slug       text UNIQUE NOT NULL,
  created_at timestamptz DEFAULT now()
);

CREATE TABLE public.org_members (
  org_id     uuid REFERENCES public.organizations(id) ON DELETE CASCADE,
  user_id    uuid REFERENCES auth.users(id) ON DELETE CASCADE,
  role       text NOT NULL CHECK (role IN ('owner', 'admin', 'member', 'viewer')),
  PRIMARY KEY (org_id, user_id)
);

CREATE TABLE public.projects (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id      uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  name        text NOT NULL,
  created_by  uuid REFERENCES auth.users(id),
  created_at  timestamptz DEFAULT now()
);

-- Index for RLS performance — always index FK columns used in policies
CREATE INDEX projects_org_id_idx ON public.projects(org_id);
CREATE INDEX org_members_user_id_idx ON public.org_members(user_id);

-- ─── 2. Enable RLS ────────────────────────────────────────────────────────
ALTER TABLE public.organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.org_members   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.projects      ENABLE ROW LEVEL SECURITY;

-- ─── 3. RLS Policies using JWT custom claims ──────────────────────────────
-- Requires a Custom Access Token Auth Hook (see Step 4) that injects
-- { "app_metadata": { "org_id": "...", "org_role": "admin" } } into the JWT.

-- Organizations: members can read their own org
CREATE POLICY "orgs: members can select"
  ON public.organizations FOR SELECT
  TO authenticated
  USING (
    id = (auth.jwt() -> 'app_metadata' ->> 'org_id')::uuid
  );

-- Projects: org members can select
CREATE POLICY "projects: org members can select"
  ON public.projects FOR SELECT
  TO authenticated
  USING (
    org_id = (auth.jwt() -> 'app_metadata' ->> 'org_id')::uuid
  );

-- Projects: admins and owners can insert
CREATE POLICY "projects: admins can insert"
  ON public.projects FOR INSERT
  TO authenticated
  WITH CHECK (
    org_id = (auth.jwt() -> 'app_metadata' ->> 'org_id')::uuid
    AND (auth.jwt() -> 'app_metadata' ->> 'org_role') IN ('owner', 'admin')
  );

-- Projects: admins and owners can delete
CREATE POLICY "projects: admins can delete"
  ON public.projects FOR DELETE
  TO authenticated
  USING (
    org_id = (auth.jwt() -> 'app_metadata' ->> 'org_id')::uuid
    AND (auth.jwt() -> 'app_metadata' ->> 'org_role') IN ('owner', 'admin')
  );

-- ─── 4. Custom Access Token Auth Hook ─────────────────────────────────────
-- A SQL function invoked by Supabase Auth before issuing a JWT.
-- Injects org_id and org_role into app_metadata.
CREATE OR REPLACE FUNCTION public.custom_access_token_hook(event jsonb)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  claims    jsonb;
  member    record;
BEGIN
  claims := event -> 'claims';

  -- Look up the user's org membership
  SELECT org_id, role INTO member
  FROM public.org_members
  WHERE user_id = (event ->> 'user_id')::uuid
  LIMIT 1;

  IF member IS NOT NULL THEN
    claims := jsonb_set(claims, '{app_metadata}',
      COALESCE(claims -> 'app_metadata', '{}'::jsonb)
      || jsonb_build_object(
           'org_id',   member.org_id,
           'org_role', member.role
         )
    );
  END IF;

  RETURN jsonb_set(event, '{claims}', claims);
END;
$$;

-- Grant execute to supabase_auth_admin (required for Auth Hooks)
GRANT EXECUTE ON FUNCTION public.custom_access_token_hook TO supabase_auth_admin;
REVOKE EXECUTE ON FUNCTION public.custom_access_token_hook FROM PUBLIC, anon, authenticated;
```

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `app_metadata.org_id` | Set by Auth Hook | UUID of the user's current organization |
| `app_metadata.org_role` | Set by Auth Hook | `owner`, `admin`, `member`, or `viewer` |
| Auth Hook type | Custom Access Token | Runs before every JWT issuance / refresh |
| Index columns | Per FK | Always index `org_id`, `user_id` on large tables |

## Example Usage

```typescript
// Client-side: after login, JWT automatically contains org_id and org_role.
// All queries are automatically scoped to the user's org via RLS.

const { data: projects } = await supabase
  .from("projects")
  .select("id, name, created_at")
  .order("created_at", { ascending: false });
// Returns only projects in the authenticated user's org — no WHERE clause needed.

// Testing RLS isolation: use two different users from different orgs
const orgAClient = createClient(url, anonKey, {
  global: { headers: { Authorization: `Bearer ${orgAUserJWT}` } },
});
const orgBClient = createClient(url, anonKey, {
  global: { headers: { Authorization: `Bearer ${orgBUserJWT}` } },
});

const { data: orgAProjects } = await orgAClient.from("projects").select("*");
const { data: orgBProjects } = await orgBClient.from("projects").select("*");
// orgAProjects and orgBProjects must never contain each other's rows
```

## See Also

- [RLS Policies Concept](../concepts/rls-policies.md)
- [RAG Vector Store Pattern](../patterns/rag-vector-store.md)
