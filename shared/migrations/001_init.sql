CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE items (
    id text PRIMARY KEY,
    source text NOT NULL,
    source_id text NOT NULL,
    url text NOT NULL,
    title text NOT NULL,
    price_cents int NOT NULL,
    ship_cents int,
    currency text DEFAULT 'USD',
    brand text,
    size_raw text,
    condition text,
    slot text,
    category text,
    usable_3d bool,
    listing jsonb NOT NULL,
    tags jsonb,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'sold', 'gone')),
    first_seen timestamptz DEFAULT now(),
    last_seen timestamptz DEFAULT now(),
    tagged_at timestamptz,
    UNIQUE (source, source_id)
);
CREATE INDEX items_active_slot_price ON items (slot, price_cents) WHERE status = 'active';
CREATE INDEX items_title_trgm ON items USING gin (title gin_trgm_ops);
CREATE INDEX items_untagged ON items (first_seen) WHERE tags IS NULL;

-- no FK to items: gen3d bakes fixture item ids that never exist in items
CREATE TABLE assets (
    item_id text PRIMARY KEY,
    json jsonb NOT NULL,
    updated_at timestamptz DEFAULT now()
);

CREATE TABLE users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email citext UNIQUE NOT NULL,
    name text NOT NULL,
    password_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
    token_hash bytea PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    last_used timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX sessions_user_id ON sessions (user_id);

CREATE TABLE profiles (
    user_id uuid PRIMARY KEY REFERENCES users ON DELETE CASCADE,
    body jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE saved_looks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users ON DELETE CASCADE,
    look jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE outfits (
    id text PRIMARY KEY,
    user_id uuid REFERENCES users ON DELETE SET NULL,
    outfit jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE login_attempts (
    key text NOT NULL,
    at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX login_attempts_key_at ON login_attempts (key, at);

CREATE TABLE scrape_runs (
    id bigserial PRIMARY KEY,
    source text NOT NULL,
    query text NOT NULL,
    slot text,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    fetched int,
    added int,
    updated int,
    errors int,
    last_error text
);
