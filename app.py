import os
import secrets
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import wraps
from io import BytesIO

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, flash, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024

DATABASE_URL = os.getenv("DATABASE_URL")
SCHEMA_READY = False

QUOTE_STATUSES = ["draft", "awaiting_approval", "approved", "execution", "printing", "completed", "delivered", "canceled"]
STATUS_LABELS = {
    "draft": "Orçamento em preparação",
    "awaiting_approval": "Aguardando aprovação",
    "approved": "Aprovado",
    "execution": "Em execução",
    "printing": "Imprimindo",
    "completed": "Concluído",
    "delivered": "Entregue",
    "canceled": "Cancelado",
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(80) UNIQUE NOT NULL,
    full_name VARCHAR(160) NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(180) NOT NULL,
    phone VARCHAR(80), email VARCHAR(180), address TEXT, notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS filaments (
    id SERIAL PRIMARY KEY,
    brand VARCHAR(120), material VARCHAR(80) NOT NULL, color VARCHAR(120) NOT NULL,
    color_hex VARCHAR(20), spool_weight_g NUMERIC(12,2) NOT NULL DEFAULT 1000,
    remaining_g NUMERIC(12,2) NOT NULL DEFAULT 0,
    purchase_cost NUMERIC(12,2) NOT NULL DEFAULT 0,
    currency VARCHAR(3) NOT NULL DEFAULT 'USD', supplier VARCHAR(160),
    min_g NUMERIC(12,2) NOT NULL DEFAULT 100, location VARCHAR(160),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS machines (
    id SERIAL PRIMARY KEY,
    name VARCHAR(160) NOT NULL, model VARCHAR(160),
    status VARCHAR(40) NOT NULL DEFAULT 'available',
    hourly_cost NUMERIC(12,2) NOT NULL DEFAULT 0,
    currency VARCHAR(3) NOT NULL DEFAULT 'USD', notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS quotes (
    id SERIAL PRIMARY KEY,
    quote_number VARCHAR(40) UNIQUE NOT NULL,
    customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
    title VARCHAR(220) NOT NULL,
    project_type VARCHAR(20) NOT NULL DEFAULT 'customer',
    status VARCHAR(40) NOT NULL DEFAULT 'draft',
    currency VARCHAR(3) NOT NULL DEFAULT 'USD',
    subtotal NUMERIC(12,2) NOT NULL DEFAULT 0,
    discount NUMERIC(12,2) NOT NULL DEFAULT 0,
    total NUMERIC(12,2) NOT NULL DEFAULT 0,
    filament_id INTEGER REFERENCES filaments(id) ON DELETE SET NULL,
    estimated_grams NUMERIC(12,2) NOT NULL DEFAULT 0,
    actual_grams NUMERIC(12,2),
    print_hours NUMERIC(12,2) NOT NULL DEFAULT 0,
    notes TEXT,
    stock_deducted BOOLEAN NOT NULL DEFAULT FALSE,
    stock_adjusted BOOLEAN NOT NULL DEFAULT FALSE,
    stock_deducted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS quote_items (
    id SERIAL PRIMARY KEY,
    quote_id INTEGER NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
    description VARCHAR(240) NOT NULL,
    quantity NUMERIC(12,2) NOT NULL DEFAULT 1,
    unit_price NUMERIC(12,2) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
    quote_id INTEGER REFERENCES quotes(id) ON DELETE SET NULL,
    customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
    project_type VARCHAR(20) NOT NULL DEFAULT 'customer',
    name VARCHAR(220) NOT NULL,
    status VARCHAR(40) NOT NULL DEFAULT 'development',
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS project_files (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    file_name VARCHAR(255) NOT NULL,
    content_type VARCHAR(120), file_size INTEGER NOT NULL,
    file_data BYTEA NOT NULL,
    version VARCHAR(40) NOT NULL DEFAULT 'v1', notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS inventory_movements (
    id SERIAL PRIMARY KEY,
    filament_id INTEGER NOT NULL REFERENCES filaments(id) ON DELETE CASCADE,
    grams NUMERIC(12,2) NOT NULL,
    movement_type VARCHAR(60) NOT NULL,
    reference_type VARCHAR(60), reference_id INTEGER, notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    sku VARCHAR(80) UNIQUE,
    name VARCHAR(220) NOT NULL,
    description TEXT,
    stock_qty INTEGER NOT NULL DEFAULT 0,
    price NUMERIC(12,2) NOT NULL DEFAULT 0,
    currency VARCHAR(3) NOT NULL DEFAULT 'USD',
    filament_id INTEGER REFERENCES filaments(id) ON DELETE SET NULL,
    grams_per_unit NUMERIC(12,2) NOT NULL DEFAULT 0,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def ensure_schema():
    global SCHEMA_READY
    if SCHEMA_READY:
        return
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
        conn.commit()
        SCHEMA_READY = True
    finally:
        conn.close()


def d(value, default="0"):
    try:
        return Decimal(str(value or default))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def money(value, currency="USD"):
    symbol = "R$" if currency == "BRL" else "$"
    return f"{symbol} {d(value):,.2f}"


app.jinja_env.globals["money"] = money
app.jinja_env.globals["status_label"] = lambda s: STATUS_LABELS.get(s, s)


def count_users():
    ensure_schema()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM users")
            return cur.fetchone()["n"]
    finally:
        conn.close()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.get("/health")
def health():
    return jsonify(status="ok", service="Sistema Legacy")


@app.route("/setup", methods=["GET", "POST"])
def setup():
    if count_users() > 0:
        return redirect(url_for("login"))
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        full_name = request.form.get("full_name", "").strip()
        password = request.form.get("password", "")
        if len(username) < 3 or len(password) < 8 or not full_name:
            flash("Informe nome, usuário e senha com pelo menos 8 caracteres.", "danger")
            return redirect(url_for("setup"))
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO users (username, full_name, password_hash) VALUES (%s,%s,%s) RETURNING id", (username, full_name, generate_password_hash(password)))
                user_id = cur.fetchone()["id"]
            conn.commit()
            session["user_id"] = user_id
            session["full_name"] = full_name
            flash("Administrador criado. Sistema Legacy pronto.", "success")
            return redirect(url_for("dashboard"))
        finally:
            conn.close()
    return render_template("login.html", setup_mode=True)


@app.route("/login", methods=["GET", "POST"])
def login():
    if count_users() == 0:
        return redirect(url_for("setup"))
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM users WHERE username=%s", (username,))
                user = cur.fetchone()
        finally:
            conn.close()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["full_name"] = user["full_name"]
            return redirect(url_for("dashboard"))
        flash("Usuário ou senha inválidos.", "danger")
    return render_template("login.html", setup_mode=False)


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
@login_required
def dashboard():
    ensure_schema()
    tab = request.args.get("tab", "dashboard")
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) n FROM customers")
            customer_count = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) n FROM quotes WHERE status NOT IN ('delivered','canceled')")
            open_quotes = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) n FROM quotes WHERE status='printing'")
            printing_count = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) n FROM filaments WHERE remaining_g <= min_g")
            low_stock_count = cur.fetchone()["n"]
            cur.execute("SELECT * FROM customers ORDER BY created_at DESC")
            customers = cur.fetchall()
            cur.execute("SELECT * FROM filaments ORDER BY created_at DESC")
            filaments = cur.fetchall()
            cur.execute("SELECT * FROM machines ORDER BY created_at DESC")
            machines = cur.fetchall()
            cur.execute("""SELECT q.*, c.name AS customer_name, f.material AS filament_material, f.color AS filament_color FROM quotes q LEFT JOIN customers c ON c.id=q.customer_id LEFT JOIN filaments f ON f.id=q.filament_id ORDER BY q.created_at DESC""")
            quotes = cur.fetchall()
            cur.execute("""SELECT p.*, c.name AS customer_name, q.quote_number, (SELECT COUNT(*) FROM project_files pf WHERE pf.project_id=p.id) AS file_count FROM projects p LEFT JOIN customers c ON c.id=p.customer_id LEFT JOIN quotes q ON q.id=p.quote_id ORDER BY p.created_at DESC""")
            projects = cur.fetchall()
            cur.execute("""SELECT pf.id, pf.project_id, pf.file_name, pf.file_size, pf.version, pf.notes, pf.created_at, p.name AS project_name FROM project_files pf JOIN projects p ON p.id=pf.project_id ORDER BY pf.created_at DESC""")
            files = cur.fetchall()
            cur.execute("""SELECT im.*, f.material, f.color FROM inventory_movements im JOIN filaments f ON f.id=im.filament_id ORDER BY im.created_at DESC LIMIT 100""")
            movements = cur.fetchall()
            cur.execute("""SELECT pr.*, p.name AS project_name FROM products pr LEFT JOIN projects p ON p.id=pr.project_id ORDER BY pr.created_at DESC""")
            products = cur.fetchall()
    finally:
        conn.close()
    return render_template("app.html", tab=tab, customer_count=customer_count, open_quotes=open_quotes, printing_count=printing_count, low_stock_count=low_stock_count, customers=customers, filaments=filaments, machines=machines, quotes=quotes, projects=projects, files=files, movements=movements, products=products, quote_statuses=QUOTE_STATUSES)


@app.post("/customers/add")
@login_required
def add_customer():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Nome do cliente é obrigatório.", "danger")
        return redirect(url_for("dashboard", tab="customers"))
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO customers (name,phone,email,address,notes) VALUES (%s,%s,%s,%s,%s)", (name, request.form.get("phone"), request.form.get("email"), request.form.get("address"), request.form.get("notes")))
        conn.commit()
    finally:
        conn.close()
    flash("Cliente cadastrado.", "success")
    return redirect(url_for("dashboard", tab="customers"))


@app.post("/filaments/add")
@login_required
def add_filament():
    material = request.form.get("material", "").strip()
    color = request.form.get("color", "").strip()
    remaining = d(request.form.get("remaining_g"))
    if not material or not color or remaining < 0:
        flash("Informe material, cor e estoque válido.", "danger")
        return redirect(url_for("dashboard", tab="stock"))
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO filaments (brand,material,color,color_hex,spool_weight_g,remaining_g,purchase_cost,currency,supplier,min_g,location) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""", (request.form.get("brand"), material, color, request.form.get("color_hex"), d(request.form.get("spool_weight_g"), "1000"), remaining, d(request.form.get("purchase_cost")), request.form.get("currency", "USD"), request.form.get("supplier"), d(request.form.get("min_g"), "100"), request.form.get("location")))
            filament_id = cur.fetchone()["id"]
            if remaining:
                cur.execute("INSERT INTO inventory_movements (filament_id,grams,movement_type,reference_type,reference_id,notes) VALUES (%s,%s,'initial_stock','filament',%s,'Estoque inicial')", (filament_id, remaining, filament_id))
        conn.commit()
    finally:
        conn.close()
    flash("Filamento adicionado.", "success")
    return redirect(url_for("dashboard", tab="stock"))


@app.post("/filaments/<int:filament_id>/adjust")
@login_required
def adjust_filament(filament_id):
    grams = d(request.form.get("grams"))
    if grams == 0:
        flash("O ajuste não pode ser zero.", "warning")
        return redirect(url_for("dashboard", tab="stock"))
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM filaments WHERE id=%s FOR UPDATE", (filament_id,))
            filament = cur.fetchone()
            if not filament:
                flash("Filamento não encontrado.", "danger")
                return redirect(url_for("dashboard", tab="stock"))
            new_remaining = d(filament["remaining_g"]) + grams
            if new_remaining < 0:
                flash("O ajuste deixaria o estoque negativo.", "danger")
                return redirect(url_for("dashboard", tab="stock"))
            cur.execute("UPDATE filaments SET remaining_g=%s WHERE id=%s", (new_remaining, filament_id))
            cur.execute("INSERT INTO inventory_movements (filament_id,grams,movement_type,reference_type,reference_id,notes) VALUES (%s,%s,'manual_adjustment','filament',%s,%s)", (filament_id, grams, filament_id, request.form.get("notes") or "Ajuste manual"))
        conn.commit()
    finally:
        conn.close()
    flash("Estoque ajustado.", "success")
    return redirect(url_for("dashboard", tab="stock"))


@app.post("/machines/add")
@login_required
def add_machine():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Nome da máquina é obrigatório.", "danger")
        return redirect(url_for("dashboard", tab="machines"))
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO machines (name,model,status,hourly_cost,currency,notes) VALUES (%s,%s,%s,%s,%s,%s)", (name, request.form.get("model"), request.form.get("status", "available"), d(request.form.get("hourly_cost")), request.form.get("currency", "USD"), request.form.get("notes")))
        conn.commit()
    finally:
        conn.close()
    flash("Máquina cadastrada.", "success")
    return redirect(url_for("dashboard", tab="machines"))


def next_quote_number(cur):
    stamp = datetime.utcnow().strftime("%Y%m")
    cur.execute("SELECT COUNT(*) AS n FROM quotes WHERE quote_number LIKE %s", (f"LEG-{stamp}-%",))
    return f"LEG-{stamp}-{cur.fetchone()['n'] + 1:04d}"


@app.post("/quotes/add")
@login_required
def add_quote():
    title = request.form.get("title", "").strip()
    project_type = request.form.get("project_type", "customer")
    customer_id = request.form.get("customer_id") or None
    qty = d(request.form.get("quantity"), "1")
    unit_price = d(request.form.get("unit_price"))
    discount = d(request.form.get("discount"))
    subtotal = qty * unit_price
    total = max(Decimal("0"), subtotal - discount)
    if not title:
        flash("Título do orçamento é obrigatório.", "danger")
        return redirect(url_for("dashboard", tab="quotes"))
    if project_type == "customer" and not customer_id:
        flash("Projeto de cliente precisa de um cliente.", "danger")
        return redirect(url_for("dashboard", tab="quotes"))
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            quote_number = next_quote_number(cur)
            cur.execute("""INSERT INTO quotes (quote_number,customer_id,title,project_type,currency,subtotal,discount,total,filament_id,estimated_grams,print_hours,notes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""", (quote_number, customer_id, title, project_type, request.form.get("currency", "USD"), subtotal, discount, total, request.form.get("filament_id") or None, d(request.form.get("estimated_grams")), d(request.form.get("print_hours")), request.form.get("notes")))
            quote_id = cur.fetchone()["id"]
            cur.execute("INSERT INTO quote_items (quote_id,description,quantity,unit_price) VALUES (%s,%s,%s,%s)", (quote_id, request.form.get("item_description") or title, qty, unit_price))
            cur.execute("INSERT INTO projects (quote_id,customer_id,project_type,name,status,description) VALUES (%s,%s,%s,%s,'development',%s)", (quote_id, customer_id, project_type, title, request.form.get("notes")))
        conn.commit()
    finally:
        conn.close()
    flash(f"Orçamento {quote_number} criado.", "success")
    return redirect(url_for("dashboard", tab="quotes"))


def transition_quote(quote_id, new_status, actual_grams=None):
    if new_status not in QUOTE_STATUSES:
        raise ValueError("Status inválido")
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM quotes WHERE id=%s FOR UPDATE", (quote_id,))
            quote = cur.fetchone()
            if not quote:
                raise ValueError("Orçamento não encontrado")
            if new_status == "printing" and not quote["stock_deducted"]:
                filament_id = quote["filament_id"]
                grams = d(quote["estimated_grams"])
                if not filament_id or grams <= 0:
                    raise ValueError("Antes de imprimir, informe filamento e consumo estimado em gramas.")
                cur.execute("SELECT * FROM filaments WHERE id=%s FOR UPDATE", (filament_id,))
                filament = cur.fetchone()
                if not filament:
                    raise ValueError("Filamento não encontrado.")
                remaining = d(filament["remaining_g"])
                if remaining < grams:
                    raise ValueError(f"Estoque insuficiente: precisa de {grams} g e há {remaining} g.")
                cur.execute("UPDATE filaments SET remaining_g=remaining_g-%s WHERE id=%s", (grams, filament_id))
                cur.execute("INSERT INTO inventory_movements (filament_id,grams,movement_type,reference_type,reference_id,notes) VALUES (%s,%s,'print_start','quote',%s,%s)", (filament_id, -grams, quote_id, f"Baixa automática {quote['quote_number']}"))
                cur.execute("UPDATE quotes SET stock_deducted=TRUE, stock_deducted_at=NOW() WHERE id=%s", (quote_id,))
            if new_status in ("completed", "delivered") and quote["stock_deducted"] and not quote["stock_adjusted"] and actual_grams not in (None, ""):
                actual = d(actual_grams)
                estimated = d(quote["estimated_grams"])
                adjustment = estimated - actual
                if actual < 0:
                    raise ValueError("Consumo real inválido.")
                if adjustment != 0 and quote["filament_id"]:
                    cur.execute("SELECT * FROM filaments WHERE id=%s FOR UPDATE", (quote["filament_id"],))
                    filament = cur.fetchone()
                    if adjustment < 0 and d(filament["remaining_g"]) < abs(adjustment):
                        raise ValueError("Estoque insuficiente para o consumo real adicional.")
                    cur.execute("UPDATE filaments SET remaining_g=remaining_g+%s WHERE id=%s", (adjustment, quote["filament_id"]))
                    cur.execute("INSERT INTO inventory_movements (filament_id,grams,movement_type,reference_type,reference_id,notes) VALUES (%s,%s,'actual_usage_adjustment','quote',%s,%s)", (quote["filament_id"], adjustment, quote_id, f"Ajuste para consumo real {actual} g"))
                cur.execute("UPDATE quotes SET actual_grams=%s, stock_adjusted=TRUE WHERE id=%s", (actual, quote_id))
            cur.execute("UPDATE quotes SET status=%s, updated_at=NOW() WHERE id=%s", (new_status, quote_id))
            cur.execute("UPDATE projects SET status=%s WHERE quote_id=%s", (new_status, quote_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.post("/quotes/<int:quote_id>/status")
@login_required
def quote_status(quote_id):
    try:
        transition_quote(quote_id, request.form.get("status", ""), request.form.get("actual_grams"))
        flash("Status atualizado.", "success")
    except ValueError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("dashboard", tab="quotes"))


@app.post("/projects/add")
@login_required
def add_project():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Nome do projeto é obrigatório.", "danger")
        return redirect(url_for("dashboard", tab="projects"))
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO projects (customer_id,project_type,name,status,description) VALUES (%s,%s,%s,%s,%s)", (request.form.get("customer_id") or None, request.form.get("project_type", "legacy"), name, request.form.get("status", "development"), request.form.get("description")))
        conn.commit()
    finally:
        conn.close()
    flash("Projeto criado.", "success")
    return redirect(url_for("dashboard", tab="projects"))


@app.post("/projects/<int:project_id>/upload")
@login_required
def upload_project_file(project_id):
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        flash("Selecione um arquivo.", "danger")
        return redirect(url_for("dashboard", tab="projects"))
    data = uploaded.read()
    if len(data) > 15 * 1024 * 1024:
        flash("Arquivo muito grande. Limite atual: 15 MB.", "danger")
        return redirect(url_for("dashboard", tab="projects"))
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO project_files (project_id,file_name,content_type,file_size,file_data,version,notes) VALUES (%s,%s,%s,%s,%s,%s,%s)", (project_id, uploaded.filename, uploaded.mimetype or "application/octet-stream", len(data), psycopg2.Binary(data), request.form.get("version", "v1"), request.form.get("notes")))
        conn.commit()
    finally:
        conn.close()
    flash("Arquivo anexado ao projeto.", "success")
    return redirect(url_for("dashboard", tab="projects"))


@app.get("/files/<int:file_id>")
@login_required
def download_file(file_id):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM project_files WHERE id=%s", (file_id,))
            item = cur.fetchone()
    finally:
        conn.close()
    if not item:
        return "Arquivo não encontrado", 404
    return send_file(BytesIO(bytes(item["file_data"])), mimetype=item["content_type"] or "application/octet-stream", as_attachment=True, download_name=item["file_name"])


@app.post("/products/add")
@login_required
def add_product():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Nome do produto é obrigatório.", "danger")
        return redirect(url_for("dashboard", tab="catalog"))
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO products (project_id,sku,name,description,stock_qty,price,currency,filament_id,grams_per_unit) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", (request.form.get("project_id") or None, request.form.get("sku") or None, name, request.form.get("description"), int(request.form.get("stock_qty") or 0), d(request.form.get("price")), request.form.get("currency", "USD"), request.form.get("filament_id") or None, d(request.form.get("grams_per_unit"))))
        conn.commit()
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        flash("Esse SKU já existe.", "danger")
        return redirect(url_for("dashboard", tab="catalog"))
    finally:
        conn.close()
    flash("Produto adicionado ao catálogo.", "success")
    return redirect(url_for("dashboard", tab="catalog"))


@app.post("/products/<int:product_id>/stock")
@login_required
def product_stock(product_id):
    qty = int(request.form.get("qty") or 0)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT stock_qty FROM products WHERE id=%s FOR UPDATE", (product_id,))
            item = cur.fetchone()
            if not item:
                flash("Produto não encontrado.", "danger")
                return redirect(url_for("dashboard", tab="catalog"))
            new_qty = item["stock_qty"] + qty
            if new_qty < 0:
                flash("Estoque de produto não pode ficar negativo.", "danger")
                return redirect(url_for("dashboard", tab="catalog"))
            cur.execute("UPDATE products SET stock_qty=%s WHERE id=%s", (new_qty, product_id))
        conn.commit()
    finally:
        conn.close()
    flash("Estoque do produto atualizado.", "success")
    return redirect(url_for("dashboard", tab="catalog"))


@app.get("/catalog")
def public_catalog():
    ensure_schema()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM products WHERE active=TRUE ORDER BY created_at DESC")
            products = cur.fetchall()
    finally:
        conn.close()
    return render_template("catalog.html", products=products)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
