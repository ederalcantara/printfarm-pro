CREATE TABLE IF NOT EXISTS production_batch_materials (
    id SERIAL PRIMARY KEY,
    batch_id INTEGER NOT NULL REFERENCES production_batches(id) ON DELETE CASCADE,
    filament_id INTEGER NOT NULL REFERENCES filaments(id) ON DELETE RESTRICT,
    grams_per_unit NUMERIC(12,2) NOT NULL,
    reserved_g NUMERIC(12,2) NOT NULL DEFAULT 0,
    consumed_g NUMERIC(12,2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(batch_id, filament_id)
);

ALTER TABLE production_batches ADD COLUMN IF NOT EXISTS invalidated_at TIMESTAMPTZ;
ALTER TABLE production_batches ADD COLUMN IF NOT EXISTS invalid_reason TEXT;

INSERT INTO production_batch_materials(batch_id,filament_id,grams_per_unit,reserved_g,consumed_g)
SELECT b.id,b.filament_id,b.grams_per_unit,b.reserved_g,
       CASE WHEN b.status='completed' THEN COALESCE(b.consumed_g,b.reserved_g) ELSE NULL END
FROM production_batches b
WHERE b.filament_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM production_batch_materials m WHERE m.batch_id=b.id
  );

UPDATE production_batches
SET invalid_reason=COALESCE(invalid_reason,'Peso histórico abaixo do mínimo de segurança de 1,00 g por unidade.')
WHERE status='completed'
  AND grams_per_unit < 1
  AND invalid_reason IS NULL;

CREATE INDEX IF NOT EXISTS idx_production_batch_materials_batch ON production_batch_materials(batch_id);
CREATE INDEX IF NOT EXISTS idx_production_batch_materials_filament ON production_batch_materials(filament_id);
