-- Temporary store for newly-generated API keys awaiting first claim.
-- Raw key lives here until the customer retrieves it (then deleted).
-- email is stored to verify ownership before returning the key.
CREATE TABLE pending_keys (
  session_id TEXT PRIMARY KEY,
  raw_key    TEXT NOT NULL,
  email      TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '24 hours')
);

-- Allow Supabase scheduled cleanups or manual purges of expired rows.
CREATE INDEX pending_keys_expires_at_idx ON pending_keys (expires_at);
