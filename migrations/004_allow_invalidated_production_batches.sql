ALTER TABLE production_batches DROP CONSTRAINT IF EXISTS production_batches_status_check;
ALTER TABLE production_batches
  ADD CONSTRAINT production_batches_status_check
  CHECK (status IN ('queued','printing','completed','cancelled','invalidated'));
