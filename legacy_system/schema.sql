CREATE TABLE IF NOT EXISTS legacy_users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT,
    role TEXT NOT NULL DEFAULT 'admin',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS legacy_customers (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    company TEXT,
    address TEXT,
    city TEXT,
    state TEXT,
    zip_code TEXT,
    instagram TEXT,
    facebook TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS legacy_filaments (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    brand TEXT,
    material TEXT NOT NULL,
    color TEXT,
    color_hex TEXT,
    sku TEXT,
    supplier TEXT,
    location TEXT,
    weight_total_g NUMERIC(12,2) NOT NULL CHECK (weight_total_g >= 0),
    weight_remaining_g NUMERIC(12,2) NOT NULL CHECK (weight_remaining_g >= 0),
    cost_per_kg NUMERIC(12,2) NOT NULL DEFAULT 0,
    currency CHAR(3) NOT NULL DEFAULT 'USD' CHECK (currency IN ('USD','BRL')),
    min_stock_g NUMERIC(12,2) NOT NULL DEFAULT 100,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS legacy_machines (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    brand TEXT,
    model TEXT,
    status TEXT NOT NULL DEFAULT 'idle' CHECK(status IN ('idle','printing','maintenance','offline')),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS legacy_projects (
    id BIGSERIAL PRIMARY KEY,
    project_number TEXT UNIQUE NOT NULL,
    project_type TEXT NOT NULL CHECK(project_type IN ('customer','legacy')),
    customer_id BIGINT REFERENCES legacy_customers(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'idea' CHECK(status IN ('idea','quoted','approved','preparing','prototype','catalog','archived')),
    currency CHAR(3) NOT NULL DEFAULT 'USD' CHECK(currency IN ('USD','BRL')),
    target_price NUMERIC(14,2),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS legacy_project_files (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL REFERENCES legacy_projects(id) ON DELETE CASCADE,
    file_type TEXT NOT NULL DEFAULT 'stl' CHECK(file_type IN ('stl','image','gcode','other')),
    original_name TEXT NOT NULL,
    storage_key TEXT,
    storage_url TEXT,
    checksum_sha256 TEXT,
    version_label TEXT NOT NULL DEFAULT 'v1',
    size_bytes BIGINT,
    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','approved','superseded')),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS legacy_quotes (
    id BIGSERIAL PRIMARY KEY,
    quote_number TEXT UNIQUE NOT NULL,
    customer_id BIGINT NOT NULL REFERENCES legacy_customers(id),
    project_id BIGINT REFERENCES legacy_projects(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','awaiting_customer_approval','approved_for_execution','preparing','printing','completed','delivered','cancelled')),
    currency CHAR(3) NOT NULL DEFAULT 'USD' CHECK (currency IN ('USD','BRL')),
    exchange_rate_to_brl NUMERIC(14,6),
    subtotal NUMERIC(14,2) NOT NULL DEFAULT 0,
    tax NUMERIC(14,2) NOT NULL DEFAULT 0,
    shipping NUMERIC(14,2) NOT NULL DEFAULT 0,
    total NUMERIC(14,2) NOT NULL DEFAULT 0,
    valid_until DATE,
    customer_notes TEXT,
    internal_notes TEXT,
    customer_approved_at TIMESTAMPTZ,
    printing_started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS legacy_quote_items (
    id BIGSERIAL PRIMARY KEY,
    quote_id BIGINT NOT NULL REFERENCES legacy_quotes(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    filament_id BIGINT REFERENCES legacy_filaments(id),
    machine_id BIGINT REFERENCES legacy_machines(id),
    project_file_id BIGINT REFERENCES legacy_project_files(id) ON DELETE SET NULL,
    estimated_filament_g NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (estimated_filament_g >= 0),
    actual_filament_g NUMERIC(12,2),
    print_time_hours NUMERIC(10,2) NOT NULL DEFAULT 0,
    labor_hours NUMERIC(10,2) NOT NULL DEFAULT 0,
    layer_height_mm NUMERIC(6,3),
    infill_percent NUMERIC(6,2),
    size_x_mm NUMERIC(10,2),
    size_y_mm NUMERIC(10,2),
    size_z_mm NUMERIC(10,2),
    unit_cost NUMERIC(14,2) NOT NULL DEFAULT 0,
    unit_price NUMERIC(14,2) NOT NULL DEFAULT 0,
    line_total NUMERIC(14,2) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS legacy_inventory_movements (
    id BIGSERIAL PRIMARY KEY,
    filament_id BIGINT NOT NULL REFERENCES legacy_filaments(id),
    quote_id BIGINT REFERENCES legacy_quotes(id),
    quote_item_id BIGINT REFERENCES legacy_quote_items(id),
    movement_type TEXT NOT NULL CHECK (movement_type IN ('in','out','adjustment')),
    quantity_g NUMERIC(12,2) NOT NULL CHECK (quantity_g > 0),
    signed_quantity_g NUMERIC(12,2) NOT NULL,
    reason TEXT NOT NULL,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (quote_item_id, reason)
);

CREATE TABLE IF NOT EXISTS legacy_catalog_products (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL REFERENCES legacy_projects(id) ON DELETE CASCADE,
    sku TEXT UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    currency CHAR(3) NOT NULL DEFAULT 'USD' CHECK(currency IN ('USD','BRL')),
    price NUMERIC(14,2) NOT NULL DEFAULT 0,
    cost NUMERIC(14,2) NOT NULL DEFAULT 0,
    ready_stock INTEGER NOT NULL DEFAULT 0 CHECK(ready_stock >= 0),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    instagram_caption TEXT,
    facebook_caption TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS legacy_finished_goods_movements (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES legacy_catalog_products(id) ON DELETE CASCADE,
    movement_type TEXT NOT NULL CHECK(movement_type IN ('in','out','adjustment')),
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    signed_quantity INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_legacy_quotes_status ON legacy_quotes(status);
CREATE INDEX IF NOT EXISTS idx_legacy_quotes_customer ON legacy_quotes(customer_id);
CREATE INDEX IF NOT EXISTS idx_legacy_inventory_filament ON legacy_inventory_movements(filament_id);
CREATE INDEX IF NOT EXISTS idx_legacy_projects_type ON legacy_projects(project_type);
CREATE INDEX IF NOT EXISTS idx_legacy_files_project ON legacy_project_files(project_id);
