-- Customers table
CREATE TABLE customers (
  stripe_customer_id TEXT PRIMARY KEY,
  email TEXT NOT NULL,
  tier TEXT NOT NULL DEFAULT 'starter',
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- API keys table (hashed only — raw key never stored)
CREATE TABLE api_keys (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  key_hash TEXT UNIQUE NOT NULL,
  customer_id TEXT NOT NULL REFERENCES customers(stripe_customer_id),
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Usage tracking table
CREATE TABLE usage (
  customer_id TEXT NOT NULL REFERENCES customers(stripe_customer_id),
  month TEXT NOT NULL,
  url_count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (customer_id, month)
);

-- Atomic upsert to avoid race conditions on concurrent scrape jobs
CREATE OR REPLACE FUNCTION increment_usage(p_customer_id TEXT, p_month TEXT)
RETURNS VOID AS $$
BEGIN
  INSERT INTO usage (customer_id, month, url_count)
  VALUES (p_customer_id, p_month, 1)
  ON CONFLICT (customer_id, month)
  DO UPDATE SET url_count = usage.url_count + 1;
END;
$$ LANGUAGE plpgsql;
