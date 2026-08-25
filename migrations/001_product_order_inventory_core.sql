-- Legacy 3D Studio: núcleo Produto -> Pedido -> Produção -> Estoque
-- Migração idempotente para PostgreSQL.

ALTER TABLE products ADD COLUMN IF NOT EXISTS image_data BYTEA;
ALTER TABLE products ADD COLUMN IF NOT EXISTS image_content_type VARCHAR(120);
ALTER TABLE products ADD COLUMN IF NOT EXISTS image_name VARCHAR(255);
ALTER TABLE products ADD COLUMN IF NOT EXISTS collection VARCHAR(30) NOT NULL DEFAULT 'catalog';
ALTER TABLE products ADD COLUMN IF NOT EXISTS display_order INTEGER NOT NULL DEFAULT 1000;
ALTER TABLE products ADD COLUMN IF NOT EXISTS fulfillment_mode VARCHAR(20) NOT NULL DEFAULT 'made_to_order';
ALTER TABLE products ADD COLUMN IF NOT EXISTS stock_min_qty INTEGER NOT NULL DEFAULT 0;
ALTER TABLE products ADD COLUMN IF NOT EXISTS reserved_stock_qty INTEGER NOT NULL DEFAULT 0;
ALTER TABLE products ADD COLUMN IF NOT EXISTS lead_time_days INTEGER;
ALTER TABLE products ADD COLUMN IF NOT EXISTS cost_estimate NUMERIC(12,2) NOT NULL DEFAULT 0;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='products_fulfillment_mode_check') THEN
    ALTER TABLE products ADD CONSTRAINT products_fulfillment_mode_check
      CHECK (fulfillment_mode IN ('ready_stock','made_to_order','both'));
  END IF;
END $$;

ALTER TABLE filaments ADD COLUMN IF NOT EXISTS reserved_g NUMERIC(12,2) NOT NULL DEFAULT 0;

-- Evolui a tabela histórica já existente sem quebrar os movimentos antigos.
ALTER TABLE inventory_movements ALTER COLUMN filament_id DROP NOT NULL;
ALTER TABLE inventory_movements ADD COLUMN IF NOT EXISTS product_id INTEGER REFERENCES products(id) ON DELETE SET NULL;
ALTER TABLE inventory_movements ADD COLUMN IF NOT EXISTS project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL;
ALTER TABLE inventory_movements ADD COLUMN IF NOT EXISTS product_qty INTEGER NOT NULL DEFAULT 0;
ALTER TABLE inventory_movements ADD COLUMN IF NOT EXISTS filament_g NUMERIC(12,2) NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_inventory_movements_product ON inventory_movements(product_id);
CREATE INDEX IF NOT EXISTS idx_inventory_movements_filament ON inventory_movements(filament_id);
CREATE INDEX IF NOT EXISTS idx_inventory_movements_project ON inventory_movements(project_id);

CREATE TABLE IF NOT EXISTS customer_requests (
 id SERIAL PRIMARY KEY,
 request_number VARCHAR(40) UNIQUE NOT NULL,
 public_token VARCHAR(80) UNIQUE NOT NULL,
 name VARCHAR(180) NOT NULL,
 email VARCHAR(180), phone VARCHAR(80),
 request_type VARCHAR(30) NOT NULL DEFAULT 'idea',
 title VARCHAR(220) NOT NULL,
 description TEXT NOT NULL,
 intended_use TEXT,
 quantity INTEGER NOT NULL DEFAULT 1,
 preferred_material VARCHAR(100), preferred_color VARCHAR(100),
 deadline VARCHAR(100), status VARCHAR(40) NOT NULL DEFAULT 'received',
 admin_notes TEXT,
 product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
 unit_price NUMERIC(12,2),
 currency VARCHAR(3),
 total_amount NUMERIC(12,2),
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS customer_request_files (
 id SERIAL PRIMARY KEY,
 request_id INTEGER NOT NULL REFERENCES customer_requests(id) ON DELETE CASCADE,
 file_name VARCHAR(255) NOT NULL,
 content_type VARCHAR(120), file_size INTEGER NOT NULL,
 file_data BYTEA NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE customer_requests ADD COLUMN IF NOT EXISTS source VARCHAR(40) NOT NULL DEFAULT 'catalog';
ALTER TABLE customer_requests ADD COLUMN IF NOT EXISTS utm_source VARCHAR(120);
ALTER TABLE customer_requests ADD COLUMN IF NOT EXISTS utm_medium VARCHAR(120);
ALTER TABLE customer_requests ADD COLUMN IF NOT EXISTS utm_campaign VARCHAR(180);
ALTER TABLE customer_requests ADD COLUMN IF NOT EXISTS customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL;
ALTER TABLE customer_requests ADD COLUMN IF NOT EXISTS quote_id INTEGER REFERENCES quotes(id) ON DELETE SET NULL;
ALTER TABLE customer_requests ADD COLUMN IF NOT EXISTS reserved_stock_qty INTEGER NOT NULL DEFAULT 0;

ALTER TABLE quote_items ADD COLUMN IF NOT EXISTS product_id INTEGER REFERENCES products(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS print_jobs (
 id SERIAL PRIMARY KEY,
 quote_id INTEGER UNIQUE NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
 project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
 machine_id INTEGER REFERENCES machines(id) ON DELETE SET NULL,
 filament_id INTEGER REFERENCES filaments(id) ON DELETE SET NULL,
 estimated_grams NUMERIC(12,2) NOT NULL DEFAULT 0,
 reserved_g NUMERIC(12,2) NOT NULL DEFAULT 0,
 actual_grams NUMERIC(12,2),
 status VARCHAR(30) NOT NULL DEFAULT 'queued',
 started_at TIMESTAMPTZ,
 completed_at TIMESTAMPTZ,
 notes TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE print_jobs ADD COLUMN IF NOT EXISTS reserved_g NUMERIC(12,2) NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS production_batches (
  id BIGSERIAL PRIMARY KEY,
  product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
  filament_id INTEGER REFERENCES filaments(id) ON DELETE SET NULL,
  project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
  quote_id INTEGER REFERENCES quotes(id) ON DELETE SET NULL,
  mode VARCHAR(20) NOT NULL DEFAULT 'stock',
  quantity INTEGER NOT NULL CHECK (quantity > 0),
  grams_per_unit NUMERIC(12,2) NOT NULL DEFAULT 0,
  reserved_g NUMERIC(12,2) NOT NULL DEFAULT 0,
  consumed_g NUMERIC(12,2) NOT NULL DEFAULT 0,
  status VARCHAR(20) NOT NULL DEFAULT 'queued',
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  CONSTRAINT production_batches_mode_check CHECK (mode IN ('stock','order')),
  CONSTRAINT production_batches_status_check CHECK (status IN ('queued','printing','completed','cancelled'))
);
CREATE INDEX IF NOT EXISTS idx_production_batches_status ON production_batches(status);
CREATE INDEX IF NOT EXISTS idx_production_batches_product ON production_batches(product_id);

CREATE TABLE IF NOT EXISTS order_events (
  id BIGSERIAL PRIMARY KEY,
  request_id INTEGER REFERENCES customer_requests(id) ON DELETE CASCADE,
  quote_id INTEGER REFERENCES quotes(id) ON DELETE CASCADE,
  event_type VARCHAR(60) NOT NULL,
  details TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_order_events_request ON order_events(request_id);
CREATE INDEX IF NOT EXISTS idx_order_events_quote ON order_events(quote_id);

UPDATE products
SET collection='exclusive'
WHERE lower(COALESCE(sku,'')) ~ '^legacy[ _-]*0*(1[0-4]|[1-9])$'
  AND collection='catalog';
