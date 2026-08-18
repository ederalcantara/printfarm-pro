CREATE TABLE IF NOT EXISTS legacy_customers (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    company TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS legacy_filaments (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    brand TEXT,
    material TEXT NOT NULL,
    color TEXT,
    color_hex TEXT,
    weight_total_g NUMERIC(12,2) NOT NULL CHECK (weight_total_g >= 0),
    weight_remaining_g NUMERIC(12,2) NOT NULL CHECK (weight_remaining_g >= 0),
    cost_per_kg NUMERIC(12,2) NOT NULL DEFAULT 0,
    currency CHAR(3) NOT NULL DEFAULT 'USD' CHECK (currency IN ('USD','BRL')),
    min_stock_g NUMERIC(12,2) NOT NULL DEFAULT 100,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS legacy_quotes (
    id BIGSERIAL PRIMARY KEY,
    quote_number TEXT UNIQUE NOT NULL,
    customer_id BIGINT REFERENCES legacy_customers(id),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN (
        'draft',
        'awaiting_customer_approval',
        'approved_for_execution',
        'preparing',
        'printing',
        'completed',
        'delivered',
        'cancelled'
    )),
    currency CHAR(3) NOT NULL DEFAULT 'USD' CHECK (currency IN ('USD','BRL')),
    exchange_rate_to_brl NUMERIC(14,6),
    subtotal NUMERIC(14,2) NOT NULL DEFAULT 0,
    total NUMERIC(14,2) NOT NULL DEFAULT 0,
    customer_approved_at TIMESTAMPTZ,
    printing_started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS legacy_quote_items (
    id BIGSERIAL PRIMARY KEY,
    quote_id BIGINT NOT NULL REFERENCES legacy_quotes(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    filament_id BIGINT REFERENCES legacy_filaments(id),
    estimated_filament_g NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (estimated_filament_g >= 0),
    unit_price NUMERIC(14,2) NOT NULL DEFAULT 0,
    line_total NUMERIC(14,2) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS legacy_inventory_movements (
    id BIGSERIAL PRIMARY KEY,
    filament_id BIGINT NOT NULL REFERENCES legacy_filaments(id),
    quote_id BIGINT REFERENCES legacy_quotes(id),
    quote_item_id BIGINT REFERENCES legacy_quote_items(id),
    movement_type TEXT NOT NULL CHECK (movement_type IN ('in','out','adjustment')),
    quantity_g NUMERIC(12,2) NOT NULL CHECK (quantity_g > 0),
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (quote_item_id, movement_type, reason)
);

CREATE INDEX IF NOT EXISTS idx_legacy_quotes_status ON legacy_quotes(status);
CREATE INDEX IF NOT EXISTS idx_legacy_inventory_filament ON legacy_inventory_movements(filament_id);
