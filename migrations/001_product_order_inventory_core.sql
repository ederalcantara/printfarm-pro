-- Legacy 3D Studio: núcleo Produto -> Pedido -> Produção -> Estoque
-- Migração idempotente para PostgreSQL.

ALTER TABLE products ADD COLUMN IF NOT EXISTS fulfillment_mode VARCHAR(20) NOT NULL DEFAULT 'made_to_order';
ALTER TABLE products ADD COLUMN IF NOT EXISTS stock_min_qty INTEGER NOT NULL DEFAULT 0;
ALTER TABLE products ADD COLUMN IF NOT EXISTS lead_time_days INTEGER;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'products_fulfillment_mode_check'
  ) THEN
    ALTER TABLE products ADD CONSTRAINT products_fulfillment_mode_check
      CHECK (fulfillment_mode IN ('ready_stock','made_to_order','both'));
  END IF;
END $$;

ALTER TABLE filaments ADD COLUMN IF NOT EXISTS reserved_g NUMERIC(12,2) NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS inventory_movements (
  id BIGSERIAL PRIMARY KEY,
  product_id BIGINT REFERENCES products(id) ON DELETE SET NULL,
  filament_id BIGINT REFERENCES filaments(id) ON DELETE SET NULL,
  project_id BIGINT,
  movement_type VARCHAR(30) NOT NULL,
  product_qty INTEGER NOT NULL DEFAULT 0,
  filament_g NUMERIC(12,2) NOT NULL DEFAULT 0,
  note TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_inventory_movements_product ON inventory_movements(product_id);
CREATE INDEX IF NOT EXISTS idx_inventory_movements_filament ON inventory_movements(filament_id);
CREATE INDEX IF NOT EXISTS idx_inventory_movements_project ON inventory_movements(project_id);

CREATE TABLE IF NOT EXISTS production_batches (
  id BIGSERIAL PRIMARY KEY,
  product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
  filament_id BIGINT REFERENCES filaments(id) ON DELETE SET NULL,
  project_id BIGINT,
  mode VARCHAR(20) NOT NULL DEFAULT 'stock',
  quantity INTEGER NOT NULL CHECK (quantity > 0),
  grams_per_unit NUMERIC(12,2) NOT NULL DEFAULT 0,
  reserved_g NUMERIC(12,2) NOT NULL DEFAULT 0,
  consumed_g NUMERIC(12,2) NOT NULL DEFAULT 0,
  status VARCHAR(20) NOT NULL DEFAULT 'queued',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ,
  CONSTRAINT production_batches_mode_check CHECK (mode IN ('stock','order')),
  CONSTRAINT production_batches_status_check CHECK (status IN ('queued','printing','completed','cancelled'))
);

CREATE INDEX IF NOT EXISTS idx_production_batches_status ON production_batches(status);
CREATE INDEX IF NOT EXISTS idx_production_batches_product ON production_batches(product_id);

-- available_g deve ser calculado como remaining_g - reserved_g.
-- Ao colocar produção na fila: incrementar reserved_g.
-- Ao iniciar/concluir: liberar reserva e registrar consumo real.
-- Ao concluir lote para estoque: incrementar products.stock_qty e registrar inventory_movements.
