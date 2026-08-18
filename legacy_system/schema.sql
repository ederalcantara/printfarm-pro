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

-- Projetos desenvolvidos pela própria Legacy para catálogo/venda.
CREATE TABLE IF NOT EXISTS legacy_projects (
    id BIGSERIAL PRIMARY KEY,
    project_code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    project_type TEXT NOT NULL CHECK (project_type IN ('customer','legacy')),
    customer_id BIGINT REFERENCES legacy_customers(id),
    quote_id BIGINT REFERENCES legacy_quotes(id),
    status TEXT NOT NULL DEFAULT 'idea' CHECK (status IN (
        'idea','development','prototype','approved','production','active_catalog','archived'
    )),
    description TEXT,
    category TEXT,
    default_currency CHAR(3) NOT NULL DEFAULT 'USD' CHECK (default_currency IN ('USD','BRL')),
    target_price NUMERIC(14,2),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (
        (project_type = 'customer' AND customer_id IS NOT NULL)
        OR project_type = 'legacy'
    )
);

CREATE TABLE IF NOT EXISTS legacy_project_files (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL REFERENCES legacy_projects(id) ON DELETE CASCADE,
    file_type TEXT NOT NULL CHECK (file_type IN ('stl','image','gcode','document','other')),
    original_name TEXT NOT NULL,
    storage_key TEXT NOT NULL,
    checksum_sha256 TEXT,
    version_label TEXT NOT NULL DEFAULT 'v1',
    file_size_bytes BIGINT,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved','superseded','archived')),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(project_id, storage_key)
);

CREATE TABLE IF NOT EXISTS legacy_project_print_profiles (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL REFERENCES legacy_projects(id) ON DELETE CASCADE,
    project_file_id BIGINT REFERENCES legacy_project_files(id),
    filament_id BIGINT REFERENCES legacy_filaments(id),
    profile_name TEXT NOT NULL DEFAULT 'default',
    size_x_mm NUMERIC(10,2),
    size_y_mm NUMERIC(10,2),
    size_z_mm NUMERIC(10,2),
    layer_height_mm NUMERIC(6,3),
    infill_percent NUMERIC(5,2),
    wall_count INTEGER,
    support_enabled BOOLEAN,
    estimated_filament_g NUMERIC(12,2) NOT NULL DEFAULT 0,
    estimated_print_minutes INTEGER,
    actual_filament_g NUMERIC(12,2),
    slicer_name TEXT,
    slicer_profile TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS legacy_catalog_products (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL UNIQUE REFERENCES legacy_projects(id),
    sku TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    price_usd NUMERIC(14,2),
    price_brl NUMERIC(14,2),
    production_cost NUMERIC(14,2) NOT NULL DEFAULT 0,
    finished_stock_qty INTEGER NOT NULL DEFAULT 0 CHECK (finished_stock_qty >= 0),
    reorder_point_qty INTEGER NOT NULL DEFAULT 0,
    instagram_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    facebook_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS legacy_finished_goods_movements (
    id BIGSERIAL PRIMARY KEY,
    catalog_product_id BIGINT NOT NULL REFERENCES legacy_catalog_products(id),
    movement_type TEXT NOT NULL CHECK (movement_type IN ('production_in','sale_out','adjustment_in','adjustment_out')),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    reference_type TEXT,
    reference_id BIGINT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_legacy_quotes_status ON legacy_quotes(status);
CREATE INDEX IF NOT EXISTS idx_legacy_inventory_filament ON legacy_inventory_movements(filament_id);
CREATE INDEX IF NOT EXISTS idx_legacy_projects_type_status ON legacy_projects(project_type, status);
CREATE INDEX IF NOT EXISTS idx_legacy_project_files_project ON legacy_project_files(project_id);
CREATE INDEX IF NOT EXISTS idx_legacy_catalog_active ON legacy_catalog_products(active);
