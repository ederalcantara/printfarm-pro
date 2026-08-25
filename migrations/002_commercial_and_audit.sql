-- Extensões comerciais, auditoria e entrega.

ALTER TABLE customers ADD COLUMN IF NOT EXISTS tags TEXT;
ALTER TABLE customers ADD COLUMN IF NOT EXISTS birthday DATE;
ALTER TABLE customers ADD COLUMN IF NOT EXISTS source VARCHAR(40);

ALTER TABLE products ADD COLUMN IF NOT EXISTS slug VARCHAR(260);
UPDATE products
SET slug = regexp_replace(regexp_replace(lower(name), '[^a-z0-9]+', '-', 'g'), '(^-|-$)', '', 'g') || '-' || id
WHERE slug IS NULL OR slug='';
CREATE UNIQUE INDEX IF NOT EXISTS idx_products_slug ON products(slug);

CREATE TABLE IF NOT EXISTS order_business (
 quote_id INTEGER PRIMARY KEY REFERENCES quotes(id) ON DELETE CASCADE,
 due_date DATE,
 delivery_method VARCHAR(30) NOT NULL DEFAULT 'pickup',
 delivery_address TEXT,
 tracking_code VARCHAR(120),
 delivery_status VARCHAR(30) NOT NULL DEFAULT 'pending',
 extra_cost NUMERIC(12,2) NOT NULL DEFAULT 0,
 labor_cost NUMERIC(12,2) NOT NULL DEFAULT 0,
 notes TEXT,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audit_log (
 id BIGSERIAL PRIMARY KEY,
 entity_type VARCHAR(60) NOT NULL,
 entity_id INTEGER,
 action VARCHAR(80) NOT NULL,
 details TEXT,
 user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log(entity_type,entity_id);
CREATE INDEX IF NOT EXISTS idx_customer_requests_source ON customer_requests(source);
CREATE INDEX IF NOT EXISTS idx_quotes_customer ON quotes(customer_id);
