#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filamanager Pro - Bilingual (EN/PT) + Multi-Currency (USD/BRL)
Version: 2.0.0
"""

from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, g
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os
from datetime import datetime
import random

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'filamanager-secret-key-2026')
app.config['UPLOAD_FOLDER'] = 'static/images'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

DATABASE = 'database.db'
_db_initialized = False
DEFAULT_LANG = 'pt'
DEFAULT_CURRENCY = 'BRL'
USD_TO_BRL = 5.0  # Taxa de conversão - ajuste conforme mercado

LANG = {
    "pt": {
        "dashboard": "Dashboard", "machines": "Máquinas", "filaments": "Estoque",
        "calculator": "Calculadora", "products": "Produtos", "orders": "Pedidos",
        "customers": "Clientes", "marketing": "Marketing", "reports": "Relatórios",
        "login": "Entrar", "logout": "Sair", "register": "Cadastrar",
        "welcome": "Bem-vindo", "total_machines": "Total de Máquinas",
        "active_machines": "Máquinas Ativas", "total_filaments": "Filamentos",
        "low_stock": "Estoque Baixo", "total_products": "Produtos",
        "total_orders": "Pedidos", "pending_orders": "Pendentes",
        "month_revenue": "Receita do Mês", "total_customers": "Clientes",
        "new_machine": "Nova Máquina", "new_filament": "Novo Filamento",
        "new_product": "Novo Produto", "new_order": "Novo Pedido",
        "new_customer": "Novo Cliente", "generate_post": "Gerar Post",
        "save": "Salvar", "cancel": "Cancelar", "delete": "Remover",
        "edit": "Editar", "name": "Nome", "brand": "Marca", "model": "Modelo",
        "status": "Status", "color": "Cor", "material": "Material",
        "price": "Preço", "cost": "Custo", "profit": "Lucro",
        "quantity": "Quantidade", "weight": "Peso", "time": "Tempo",
        "settings": "Configurações", "language": "Idioma",
        "currency": "Moeda", "usd": "Dólar", "brl": "Real",
        "idle": "Livre", "printing": "Imprimindo", "maintenance": "Manutenção",
        "pending": "Pendente", "completed": "Concluído", "cancelled": "Cancelado",
        "normal": "Normal", "high": "Alta", "low": "Baixa",
        "available": "Disponível", "finished": "Acabado", "ordered": "Pedido",
        "public": "Público", "private": "Privado", "featured": "Destaque",
        "cost_calculator": "Calculadora de Custo",
        "calculate_price": "Calcular Preço", "copy_price": "Copiar Preço",
        "filament_cost": "Filamento", "electricity_cost": "Eletricidade",
        "labor_cost": "Mão de Obra", "depreciation": "Depreciação",
        "maintenance_cost": "Manutenção", "failed_print": "Falhas",
        "overhead": "Overhead", "total_cost": "CUSTO TOTAL",
        "price_per_unit": "Preço por Unidade", "total_price": "Total",
        "estimated_profit": "LUCRO ESTIMADO", "margin": "Margem",
        "print_time": "Tempo de Impressão", "layer_height": "Altura de Camada",
        "infill": "Preenchimento", "wall_count": "Paredes",
        "support": "Suporte", "yes": "Sim", "no": "Não",
        "category": "Categoria", "tags": "Tags", "description": "Descrição",
        "sku": "SKU", "supplier": "Fornecedor", "location": "Localização",
        "min_stock": "Estoque Mínimo", "diameter": "Diâmetro",
        "bed_size": "Mesa", "nozzle": "Bico", "max_temp": "Temp. Máxima",
        "purchase_date": "Data de Compra", "purchase_price": "Preço de Compra",
        "hours_used": "Horas de Uso", "serial": "Número de Série",
        "customer_name": "Nome do Cliente", "customer_email": "Email",
        "customer_phone": "Telefone", "address": "Endereço",
        "city": "Cidade", "state": "Estado", "zip": "CEP",
        "instagram": "Instagram", "facebook": "Facebook",
        "order_number": "Pedido", "priority": "Prioridade",
        "platform": "Plataforma", "content": "Conteúdo",
        "hashtags": "Hashtags", "draft": "Rascunho", "posted": "Publicado",
        "copy": "Copiar", "publish": "Publicar",
        "revenue_by_month": "Receita por Mês", "top_products": "Produtos Mais Vendidos",
        "filament_usage": "Uso de Filamentos", "machine_usage": "Ocupação das Máquinas",
        "orders_count": "Pedidos", "revenue": "Receita", "hours": "Horas",
        "electricity_rate": "Custo Energia (kWh)", "labor_rate": "Mão de Obra (h)",
        "machine_depreciation_rate": "Depreciação Máquina (h)",
        "maintenance_rate": "Manutenção (h)", "failed_rate": "Taxa de Falhas (%)",
        "overhead_rate": "Overhead (%)", "min_margin": "Margem Mínima (%)",
        "shipping_cost": "Frete Padrão", "updated": "Atualizado",
        "select": "Selecione...", "required_field": "Campo obrigatório",
        "success": "Sucesso", "error": "Erro", "warning": "Atenção",
        "info": "Informação", "created": "criado", "updated": "atualizado",
        "deleted": "removido", "not_found": "não encontrado",
        "access_denied": "Acesso negado", "login_required": "Faça login",
        "invalid_credentials": "Usuário ou senha incorretos",
        "username_exists": "Nome de usuário já existe",
        "account_created": "Conta criada com sucesso",
        "machine_created": "Máquina cadastrada", "machine_updated": "Máquina atualizada",
        "filament_created": "Filamento cadastrado", "filament_updated": "Filamento atualizado",
        "product_created": "Produto cadastrado", "product_updated": "Produto atualizado",
        "order_created": "Pedido criado", "status_updated": "Status atualizado",
        "customer_created": "Cliente cadastrado", "settings_updated": "Configurações atualizadas",
        "post_generated": "Post gerado", "stock_alert": "Alerta de estoque",
        "free": "Livre", "occupied": "Ocupada", "decorative": "Decorativo",
        "standard": "Padrão", "fast": "Rápido", "high_quality": "Alta qualidade",
        "resistant": "Resistente", "solid": "Sólido",
        "decoration": "Decoração", "utilities": "Utilitários", "cosplay": "Cosplay",
        "prototypes": "Protótipos", "toys": "Brinquedos",
        "organizers": "Organizadores", "supports": "Suportes",
        "keychains": "Chaveiros", "lamps": "Luminárias", "other": "Outro",
        "tree": "Tree", "normal": "Normal", "custom": "Personalizado",
        "present": "Presente", "home": "Casa", "office": "Escritório",
        "3d_printing": "Impressão 3D", "maker": "Maker", "technology": "Tecnologia",
        "innovation": "Inovação", "custom_made": "Personalizado"
    },
    "en": {
        "dashboard": "Dashboard", "machines": "Machines", "filaments": "Stock",
        "calculator": "Calculator", "products": "Products", "orders": "Orders",
        "customers": "Customers", "marketing": "Marketing", "reports": "Reports",
        "login": "Login", "logout": "Logout", "register": "Register",
        "welcome": "Welcome", "total_machines": "Total Machines",
        "active_machines": "Active Machines", "total_filaments": "Filaments",
        "low_stock": "Low Stock", "total_products": "Products",
        "total_orders": "Orders", "pending_orders": "Pending",
        "month_revenue": "Monthly Revenue", "total_customers": "Customers",
        "new_machine": "New Machine", "new_filament": "New Filament",
        "new_product": "New Product", "new_order": "New Order",
        "new_customer": "New Customer", "generate_post": "Generate Post",
        "save": "Save", "cancel": "Cancel", "delete": "Delete",
        "edit": "Edit", "name": "Name", "brand": "Brand", "model": "Model",
        "status": "Status", "color": "Color", "material": "Material",
        "price": "Price", "cost": "Cost", "profit": "Profit",
        "quantity": "Quantity", "weight": "Weight", "time": "Time",
        "settings": "Settings", "language": "Language",
        "currency": "Currency", "usd": "USD", "brl": "BRL",
        "idle": "Idle", "printing": "Printing", "maintenance": "Maintenance",
        "pending": "Pending", "completed": "Completed", "cancelled": "Cancelled",
        "normal": "Normal", "high": "High", "low": "Low",
        "available": "Available", "finished": "Finished", "ordered": "Ordered",
        "public": "Public", "private": "Private", "featured": "Featured",
        "cost_calculator": "Cost Calculator",
        "calculate_price": "Calculate Price", "copy_price": "Copy Price",
        "filament_cost": "Filament", "electricity_cost": "Electricity",
        "labor_cost": "Labor", "depreciation": "Depreciation",
        "maintenance_cost": "Maintenance", "failed_print": "Failed Prints",
        "overhead": "Overhead", "total_cost": "TOTAL COST",
        "price_per_unit": "Price per Unit", "total_price": "Total",
        "estimated_profit": "ESTIMATED PROFIT", "margin": "Margin",
        "print_time": "Print Time", "layer_height": "Layer Height",
        "infill": "Infill", "wall_count": "Walls",
        "support": "Support", "yes": "Yes", "no": "No",
        "category": "Category", "tags": "Tags", "description": "Description",
        "sku": "SKU", "supplier": "Supplier", "location": "Location",
        "min_stock": "Min Stock", "diameter": "Diameter",
        "bed_size": "Bed Size", "nozzle": "Nozzle", "max_temp": "Max Temp",
        "purchase_date": "Purchase Date", "purchase_price": "Purchase Price",
        "hours_used": "Hours Used", "serial": "Serial Number",
        "customer_name": "Customer Name", "customer_email": "Email",
        "customer_phone": "Phone", "address": "Address",
        "city": "City", "state": "State", "zip": "ZIP",
        "instagram": "Instagram", "facebook": "Facebook",
        "order_number": "Order", "priority": "Priority",
        "platform": "Platform", "content": "Content",
        "hashtags": "Hashtags", "draft": "Draft", "posted": "Posted",
        "copy": "Copy", "publish": "Publish",
        "revenue_by_month": "Revenue by Month", "top_products": "Top Products",
        "filament_usage": "Filament Usage", "machine_usage": "Machine Usage",
        "orders_count": "Orders", "revenue": "Revenue", "hours": "Hours",
        "electricity_rate": "Electricity Cost (kWh)", "labor_rate": "Labor Cost (h)",
        "machine_depreciation_rate": "Machine Depreciation (h)",
        "maintenance_rate": "Maintenance (h)", "failed_rate": "Failure Rate (%)",
        "overhead_rate": "Overhead (%)", "min_margin": "Min Margin (%)",
        "shipping_cost": "Default Shipping", "updated": "Updated",
        "select": "Select...", "required_field": "Required field",
        "success": "Success", "error": "Error", "warning": "Warning",
        "info": "Info", "created": "created", "updated": "updated",
        "deleted": "deleted", "not_found": "not found",
        "access_denied": "Access denied", "login_required": "Please login",
        "invalid_credentials": "Invalid username or password",
        "username_exists": "Username already exists",
        "account_created": "Account created successfully",
        "machine_created": "Machine registered", "machine_updated": "Machine updated",
        "filament_created": "Filament registered", "filament_updated": "Filament updated",
        "product_created": "Product registered", "product_updated": "Product updated",
        "order_created": "Order created", "status_updated": "Status updated",
        "customer_created": "Customer registered", "settings_updated": "Settings updated",
        "post_generated": "Post generated", "stock_alert": "Stock alert",
        "free": "Free", "occupied": "Occupied", "decorative": "Decorative",
        "standard": "Standard", "fast": "Fast", "high_quality": "High quality",
        "resistant": "Resistant", "solid": "Solid",
        "decoration": "Decoration", "utilities": "Utilities", "cosplay": "Cosplay",
        "prototypes": "Prototypes", "toys": "Toys",
        "organizers": "Organizers", "supports": "Supports",
        "keychains": "Keychains", "lamps": "Lamps", "other": "Other",
        "tree": "Tree", "normal": "Normal", "custom": "Custom",
        "present": "Gift", "home": "Home", "office": "Office",
        "3d_printing": "3D Printing", "maker": "Maker", "technology": "Technology",
        "innovation": "Innovation", "custom_made": "Custom Made"
    }
}

CURRENCY_SYMBOL = {"BRL": "R$", "USD": "$"}

def get_lang():
    return session.get("lang", DEFAULT_LANG)

def get_currency():
    return session.get("currency", DEFAULT_CURRENCY)

def t(key):
    lang = get_lang()
    return LANG.get(lang, LANG[DEFAULT_LANG]).get(key, key)

def format_currency(value):
    if value is None:
        value = 0
    curr = get_currency()
    sym = CURRENCY_SYMBOL.get(curr, "R$")
    if curr == "USD":
        value = value / USD_TO_BRL
    return f"{sym} {value:,.2f}"

def convert_to_brl(value):
    if value is None:
        return 0
    curr = get_currency()
    if curr == "USD":
        return value * USD_TO_BRL
    return value

app.jinja_env.globals.update(t=t, format_currency=format_currency, get_lang=get_lang, get_currency=get_currency)

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            email TEXT,
            full_name TEXT,
            role TEXT DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            active INTEGER DEFAULT 1
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS machines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            brand TEXT NOT NULL,
            model TEXT NOT NULL,
            serial_number TEXT,
            status TEXT DEFAULT 'idle',
            bed_size_x REAL DEFAULT 220,
            bed_size_y REAL DEFAULT 220,
            bed_size_z REAL DEFAULT 250,
            nozzle_diameter REAL DEFAULT 0.4,
            max_temp_nozzle REAL DEFAULT 260,
            max_temp_bed REAL DEFAULT 110,
            filament_types TEXT DEFAULT 'PLA,ABS,PETG',
            purchase_date DATE,
            purchase_price REAL,
            hours_used REAL DEFAULT 0,
            maintenance_hours REAL DEFAULT 0,
            last_maintenance DATE,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS filaments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            brand TEXT NOT NULL,
            material TEXT NOT NULL,
            color TEXT NOT NULL,
            color_hex TEXT DEFAULT '#FF6B35',
            diameter REAL DEFAULT 1.75,
            weight_kg REAL DEFAULT 1.0,
            weight_remaining_kg REAL DEFAULT 1.0,
            price_per_kg REAL NOT NULL,
            spool_price REAL,
            temperature_range TEXT,
            bed_temperature TEXT,
            sku TEXT,
            supplier TEXT,
            location TEXT,
            min_stock REAL DEFAULT 0.2,
            status TEXT DEFAULT 'available',
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            category TEXT,
            tags TEXT,
            stl_file_path TEXT,
            image_path TEXT,
            print_time_hours REAL,
            filament_weight_g REAL,
            filament_id INTEGER,
            machine_id INTEGER,
            layer_height REAL DEFAULT 0.2,
            infill_percent REAL DEFAULT 20,
            wall_count INTEGER DEFAULT 3,
            support_needed INTEGER DEFAULT 0,
            support_type TEXT,
            base_cost REAL,
            suggested_price REAL,
            profit_margin REAL DEFAULT 50,
            is_public INTEGER DEFAULT 1,
            featured INTEGER DEFAULT 0,
            views INTEGER DEFAULT 0,
            orders_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS print_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number TEXT UNIQUE NOT NULL,
            product_id INTEGER,
            customer_name TEXT,
            customer_email TEXT,
            customer_phone TEXT,
            quantity INTEGER DEFAULT 1,
            machine_id INTEGER,
            filament_id INTEGER,
            status TEXT DEFAULT 'pending',
            priority TEXT DEFAULT 'normal',
            print_time_estimated REAL,
            print_time_actual REAL,
            filament_used_g REAL,
            electricity_cost REAL,
            labor_cost REAL,
            total_cost REAL,
            price_charged REAL,
            profit REAL,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cost_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            electricity_cost_per_kwh REAL DEFAULT 0.15,
            labor_cost_per_hour REAL DEFAULT 3.00,
            machine_depreciation_per_hour REAL DEFAULT 0.40,
            maintenance_cost_per_hour REAL DEFAULT 0.30,
            failed_print_rate REAL DEFAULT 10.0,
            overhead_percent REAL DEFAULT 20.0,
            min_profit_margin REAL DEFAULT 30.0,
            default_shipping_cost REAL DEFAULT 3.00,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT,
            phone TEXT,
            address TEXT,
            city TEXT,
            state TEXT,
            zip_code TEXT,
            instagram TEXT,
            facebook TEXT,
            notes TEXT,
            total_orders INTEGER DEFAULT 0,
            total_spent REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS marketing_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT,
            platform TEXT,
            product_id INTEGER,
            image_path TEXT,
            hashtags TEXT,
            scheduled_date TIMESTAMP,
            posted_date TIMESTAMP,
            status TEXT DEFAULT 'draft',
            engagement_likes INTEGER DEFAULT 0,
            engagement_comments INTEGER DEFAULT 0,
            engagement_shares INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS maintenance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_id INTEGER NOT NULL,
            maintenance_type TEXT NOT NULL,
            description TEXT,
            parts_replaced TEXT,
            cost REAL,
            hours_spent REAL,
            performed_by TEXT,
            next_maintenance_date DATE,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute('INSERT OR IGNORE INTO users (id, username, password, email, full_name, role) VALUES (1, ?, ?, ?, ?, ?)',
                   ('admin', generate_password_hash('admin123'), 'admin@filamanager.com', 'Administrator', 'admin'))

    cursor.execute('INSERT OR IGNORE INTO cost_settings (id) VALUES (1')

    conn.commit()
    conn.close()
    print('Database initialized!')

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash(t('login_required'), 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        conn = get_db()
        user = conn.execute('SELECT role FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        conn.close()
        if not user or user['role'] != 'admin':
            flash(t('access_denied'), 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function


# ============================================================
# DATABASE AUTO-INITIALIZATION (for Render/Gunicorn)
# ============================================================

@app.before_request
def ensure_db():
    global _db_initialized
    if not _db_initialized:
        init_db()
        _db_initialized = True

# ============================================================
# LANGUAGE & CURRENCY SWITCHER
# ============================================================

@app.route('/set-lang/<lang>')
def set_lang(lang):
    if lang in ["pt", "en"]:
        session['lang'] = lang
    return redirect(request.referrer or url_for("dashboard"))

@app.route('/set-currency/<currency>')
def set_currency(currency):
    if currency in ["BRL", "USD"]:
        session['currency'] = currency
    return redirect(request.referrer or url_for("dashboard"))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE username = ? AND active = 1', (username,)).fetchone()
        conn.close()
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            flash(t('welcome') + ', ' + user['full_name'] + '!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash(t('invalid_credentials'), 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash(t('logout'), 'info')
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']
        full_name = request.form['full_name']
        conn = get_db()
        existing = conn.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
        if existing:
            flash(t('username_exists'), 'danger')
            conn.close()
            return render_template('register.html')
        hashed = generate_password_hash(password)
        conn.execute('INSERT INTO users (username, password, email, full_name) VALUES (?, ?, ?, ?)', (username, hashed, email, full_name))
        conn.commit()
        conn.close()
        flash(t('account_created'), 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db()
    stats = {
        'total_machines': conn.execute('SELECT COUNT(*) as count FROM machines').fetchone()['count'],
        'active_machines': conn.execute("SELECT COUNT(*) as count FROM machines WHERE status = 'printing'").fetchone()['count'],
        'total_filaments': conn.execute('SELECT COUNT(*) as count FROM filaments').fetchone()['count'],
        'low_stock': conn.execute('SELECT COUNT(*) as count FROM filaments WHERE weight_remaining_kg <= min_stock').fetchone()['count'],
        'total_products': conn.execute('SELECT COUNT(*) as count FROM products').fetchone()['count'],
        'total_orders': conn.execute('SELECT COUNT(*) as count FROM print_jobs').fetchone()['count'],
        'pending_orders': conn.execute("SELECT COUNT(*) as count FROM print_jobs WHERE status = 'pending'").fetchone()['count'],
        'month_revenue': conn.execute('''SELECT COALESCE(SUM(price_charged), 0) as total FROM print_jobs WHERE status = 'completed' AND strftime("%Y-%m", completed_at) = strftime("%Y-%m", 'now')''').fetchone()['total'],
        'total_customers': conn.execute('SELECT COUNT(*) as count FROM customers').fetchone()['count'],
    }
    machines = conn.execute('SELECT * FROM machines ORDER BY created_at DESC LIMIT 5').fetchall()
    recent_orders = conn.execute('''SELECT pj.*, p.name as product_name, m.name as machine_name FROM print_jobs pj LEFT JOIN products p ON pj.product_id = p.id LEFT JOIN machines m ON pj.machine_id = m.id ORDER BY pj.created_at DESC LIMIT 10''').fetchall()
    low_stock_filaments = conn.execute('SELECT * FROM filaments WHERE weight_remaining_kg <= min_stock ORDER BY weight_remaining_kg ASC').fetchall()
    conn.close()
    return render_template('dashboard.html', stats=stats, machines=machines, recent_orders=recent_orders, low_stock=low_stock_filaments)

@app.route('/machines')
@login_required
def machines():
    conn = get_db()
    all_machines = conn.execute('SELECT * FROM machines ORDER BY name').fetchall()
    conn.close()
    return render_template('machines.html', machines=all_machines)

@app.route('/machines/add', methods=['GET', 'POST'])
@login_required
def add_machine():
    if request.method == 'POST':
        conn = get_db()
        conn.execute('''INSERT INTO machines (name, brand, model, serial_number, status, bed_size_x, bed_size_y, bed_size_z, nozzle_diameter, max_temp_nozzle, max_temp_bed, filament_types, purchase_date, purchase_price, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (
            request.form['name'], request.form['brand'], request.form['model'],
            request.form.get('serial_number'), request.form.get('status', 'idle'),
            request.form.get('bed_size_x', 220), request.form.get('bed_size_y', 220),
            request.form.get('bed_size_z', 250), request.form.get('nozzle_diameter', 0.4),
            request.form.get('max_temp_nozzle', 260), request.form.get('max_temp_bed', 110),
            request.form.get('filament_types', 'PLA,ABS,PETG'),
            request.form.get('purchase_date'), request.form.get('purchase_price'),
            request.form.get('notes')))
        conn.commit()
        conn.close()
        flash(t('machine_created'), 'success')
        return redirect(url_for('machines'))
    return render_template('machine_form.html', machine=None)

@app.route('/machines/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_machine(id):
    conn = get_db()
    machine = conn.execute('SELECT * FROM machines WHERE id = ?', (id,)).fetchone()
    if request.method == 'POST':
        conn.execute('''UPDATE machines SET name=?, brand=?, model=?, serial_number=?, status=?, bed_size_x=?, bed_size_y=?, bed_size_z=?, nozzle_diameter=?, max_temp_nozzle=?, max_temp_bed=?, filament_types=?, purchase_date=?, purchase_price=?, notes=?, hours_used=?, maintenance_hours=? WHERE id=?''', (
            request.form['name'], request.form['brand'], request.form['model'],
            request.form.get('serial_number'), request.form.get('status'),
            request.form.get('bed_size_x'), request.form.get('bed_size_y'),
            request.form.get('bed_size_z'), request.form.get('nozzle_diameter'),
            request.form.get('max_temp_nozzle'), request.form.get('max_temp_bed'),
            request.form.get('filament_types'), request.form.get('purchase_date'),
            request.form.get('purchase_price'), request.form.get('notes'),
            request.form.get('hours_used', 0), request.form.get('maintenance_hours', 0), id))
        conn.commit()
        conn.close()
        flash(t('machine_updated'), 'success')
        return redirect(url_for('machines'))
    conn.close()
    return render_template('machine_form.html', machine=machine)

@app.route('/machines/delete/<int:id>')
@login_required
def delete_machine(id):
    conn = get_db()
    conn.execute('DELETE FROM machines WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    flash(t('deleted'), 'info')
    return redirect(url_for('machines'))

@app.route('/filaments')
@login_required
def filaments():
    conn = get_db()
    all_filaments = conn.execute('SELECT * FROM filaments ORDER BY material, color').fetchall()
    conn.close()
    return render_template('filaments.html', filaments=all_filaments)

@app.route('/filaments/add', methods=['GET', 'POST'])
@login_required
def add_filament():
    if request.method == 'POST':
        conn = get_db()
        conn.execute('''INSERT INTO filaments (name, brand, material, color, color_hex, diameter, weight_kg, weight_remaining_kg, price_per_kg, spool_price, temperature_range, bed_temperature, sku, supplier, location, min_stock, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (
            request.form['name'], request.form['brand'], request.form['material'],
            request.form['color'], request.form.get('color_hex', '#FF6B35'),
            request.form.get('diameter', 1.75), request.form.get('weight_kg', 1.0),
            request.form.get('weight_remaining_kg', 1.0), request.form['price_per_kg'],
            request.form.get('spool_price'), request.form.get('temperature_range'),
            request.form.get('bed_temperature'), request.form.get('sku'),
            request.form.get('supplier'), request.form.get('location'),
            request.form.get('min_stock', 0.2), request.form.get('notes')))
        conn.commit()
        conn.close()
        flash(t('filament_created'), 'success')
        return redirect(url_for('filaments'))
    return render_template('filament_form.html', filament=None)

@app.route('/filaments/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_filament(id):
    conn = get_db()
    filament = conn.execute('SELECT * FROM filaments WHERE id = ?', (id,)).fetchone()
    if request.method == 'POST':
        conn.execute('''UPDATE filaments SET name=?, brand=?, material=?, color=?, color_hex=?, diameter=?, weight_kg=?, weight_remaining_kg=?, price_per_kg=?, spool_price=?, temperature_range=?, bed_temperature=?, sku=?, supplier=?, location=?, min_stock=?, status=?, notes=? WHERE id=?''', (
            request.form['name'], request.form['brand'], request.form['material'],
            request.form['color'], request.form.get('color_hex'),
            request.form.get('diameter'), request.form.get('weight_kg'),
            request.form.get('weight_remaining_kg'), request.form['price_per_kg'],
            request.form.get('spool_price'), request.form.get('temperature_range'),
            request.form.get('bed_temperature'), request.form.get('sku'),
            request.form.get('supplier'), request.form.get('location'),
            request.form.get('min_stock'), request.form.get('status', 'available'),
            request.form.get('notes'), id))
        conn.commit()
        conn.close()
        flash(t('filament_updated'), 'success')
        return redirect(url_for('filaments'))
    conn.close()
    return render_template('filament_form.html', filament=filament)

@app.route('/filaments/delete/<int:id>')
@login_required
def delete_filament(id):
    conn = get_db()
    conn.execute('DELETE FROM filaments WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    flash(t('deleted'), 'info')
    return redirect(url_for('filaments'))

@app.route('/calculator', methods=['GET', 'POST'])
@login_required
def calculator():
    conn = get_db()
    cost_settings = conn.execute('SELECT * FROM cost_settings WHERE id = 1').fetchone()
    filaments = conn.execute('SELECT * FROM filaments WHERE status = "available"').fetchall()
    machines = conn.execute('SELECT * FROM machines').fetchall()
    result = None
    if request.method == 'POST':
        filament_id = int(request.form['filament_id'])
        weight_g = float(request.form['weight_g'])
        print_time_hours = float(request.form['print_time_hours'])
        machine_id = int(request.form['machine_id'])
        layer_height = float(request.form.get('layer_height', 0.2))
        infill = float(request.form.get('infill', 20))
        quantity = int(request.form.get('quantity', 1))
        profit_margin = float(request.form.get('profit_margin', cost_settings['min_profit_margin']))
        filament = conn.execute('SELECT * FROM filaments WHERE id = ?', (filament_id,)).fetchone()
        machine = conn.execute('SELECT * FROM machines WHERE id = ?', (machine_id,)).fetchone()
        filament_cost = (weight_g / 1000) * filament["price_per_kg"]
        electricity_cost = print_time_hours * (300 / 1000) * cost_settings["electricity_cost_per_kwh"]
        labor_cost = print_time_hours * cost_settings["labor_cost_per_hour"]
        machine_depreciation = print_time_hours * cost_settings["machine_depreciation_per_hour"]
        maintenance_cost = print_time_hours * cost_settings["maintenance_cost_per_hour"]
        subtotal = filament_cost + electricity_cost + labor_cost + machine_depreciation + maintenance_cost
        failed_print_cost = subtotal * (cost_settings["failed_print_rate"] / 100)
        overhead = subtotal * (cost_settings["overhead_percent"] / 100)
        total_cost = subtotal + failed_print_cost + overhead
        total_cost_all = total_cost * quantity
        price_per_unit = total_cost * (1 + profit_margin / 100)
        total_price = price_per_unit * quantity
        profit = total_price - total_cost_all
        result = {
            "filament_name": filament["name"],
            "machine_name": machine["name"],
            "weight_g": weight_g,
            "print_time_hours": print_time_hours,
            "quantity": quantity,
            "profit_margin": profit_margin,
            "filament_cost": round(filament_cost, 2),
            "electricity_cost": round(electricity_cost, 2),
            "labor_cost": round(labor_cost, 2),
            "machine_depreciation": round(machine_depreciation, 2),
            "maintenance_cost": round(maintenance_cost, 2),
            "failed_print_cost": round(failed_print_cost, 2),
            "overhead": round(overhead, 2),
            "total_cost": round(total_cost, 2),
            "total_cost_all": round(total_cost_all, 2),
            "price_per_unit": round(price_per_unit, 2),
            "total_price": round(total_price, 2),
            "profit": round(profit, 2),
            "profit_percent": round((profit / total_price) * 100, 1)
        }
    conn.close()
    return render_template('calculator.html', cost_settings=cost_settings, filaments=filaments, machines=machines, result=result)

@app.route('/calculator/settings', methods=['GET', 'POST'])
@login_required
def calculator_settings():
    conn = get_db()
    if request.method == 'POST':
        conn.execute('''UPDATE cost_settings SET electricity_cost_per_kwh=?, labor_cost_per_hour=?, machine_depreciation_per_hour=?, maintenance_cost_per_hour=?, failed_print_rate=?, overhead_percent=?, min_profit_margin=?, default_shipping_cost=?, updated_at=CURRENT_TIMESTAMP WHERE id=1''', (
            request.form['electricity_cost_per_kwh'], request.form['labor_cost_per_hour'],
            request.form['machine_depreciation_per_hour'], request.form['maintenance_cost_per_hour'],
            request.form['failed_print_rate'], request.form['overhead_percent'],
            request.form['min_profit_margin'], request.form['default_shipping_cost']))
        conn.commit()
        flash(t('settings_updated'), 'success')
    settings = conn.execute('SELECT * FROM cost_settings WHERE id = 1').fetchone()
    conn.close()
    return render_template('calculator_settings.html', settings=settings)

@app.route('/products')
@login_required
def products():
    conn = get_db()
    all_products = conn.execute('''SELECT p.*, f.name as filament_name, f.color, m.name as machine_name FROM products p LEFT JOIN filaments f ON p.filament_id = f.id LEFT JOIN machines m ON p.machine_id = m.id ORDER BY p.created_at DESC''').fetchall()
    conn.close()
    return render_template('products.html', products=all_products)

@app.route('/products/add', methods=['GET', 'POST'])
@login_required
def add_product():
    conn = get_db()
    filaments = conn.execute('SELECT * FROM filaments WHERE status = "available"').fetchall()
    machines = conn.execute('SELECT * FROM machines').fetchall()
    if request.method == 'POST':
        filament_id = int(request.form['filament_id'])
        weight_g = float(request.form['filament_weight_g'])
        print_time = float(request.form['print_time_hours'])
        machine_id = int(request.form['machine_id'])
        filament = conn.execute('SELECT * FROM filaments WHERE id = ?', (filament_id,)).fetchone()
        cost_settings = conn.execute('SELECT * FROM cost_settings WHERE id = 1').fetchone()
        filament_cost = (weight_g / 1000) * filament["price_per_kg"]
        electricity_cost = print_time * 0.3 * cost_settings["electricity_cost_per_kwh"]
        labor_cost = print_time * cost_settings["labor_cost_per_hour"]
        depreciation = print_time * cost_settings["machine_depreciation_per_hour"]
        maintenance = print_time * cost_settings["maintenance_cost_per_hour"]
        base_cost = filament_cost + electricity_cost + labor_cost + depreciation + maintenance
        base_cost = base_cost * (1 + cost_settings["failed_print_rate"] / 100)
        base_cost = base_cost * (1 + cost_settings["overhead_percent"] / 100)
        profit_margin = float(request.form.get('profit_margin', 50))
        suggested_price = base_cost * (1 + profit_margin / 100)
        conn.execute('''INSERT INTO products (name, description, category, tags, print_time_hours, filament_weight_g, filament_id, machine_id, layer_height, infill_percent, wall_count, support_needed, support_type, base_cost, suggested_price, profit_margin, is_public, featured, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (
            request.form['name'], request.form.get('description'), request.form.get('category'),
            request.form.get('tags'), print_time, weight_g, filament_id, machine_id,
            request.form.get('layer_height', 0.2), request.form.get('infill_percent', 20),
            request.form.get('wall_count', 3), request.form.get('support_needed', 0),
            request.form.get('support_type'), round(base_cost, 2), round(suggested_price, 2),
            profit_margin, request.form.get('is_public', 1), request.form.get('featured', 0),
            request.form.get('notes')))
        conn.commit()
        conn.close()
        flash(t('product_created'), 'success')
        return redirect(url_for('products'))
    conn.close()
    return render_template('product_form.html', product=None, filaments=filaments, machines=machines)

@app.route('/products/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_product(id):
    conn = get_db()
    product = conn.execute('SELECT * FROM products WHERE id = ?', (id,)).fetchone()
    filaments = conn.execute('SELECT * FROM filaments WHERE status = "available"').fetchall()
    machines = conn.execute('SELECT * FROM machines').fetchall()
    if request.method == 'POST':
        conn.execute('''UPDATE products SET name=?, description=?, category=?, tags=?, print_time_hours=?, filament_weight_g=?, filament_id=?, machine_id=?, layer_height=?, infill_percent=?, wall_count=?, support_needed=?, support_type=?, base_cost=?, suggested_price=?, profit_margin=?, is_public=?, featured=?, notes=? WHERE id=?''', (
            request.form['name'], request.form.get('description'), request.form.get('category'),
            request.form.get('tags'), request.form.get('print_time_hours'),
            request.form.get('filament_weight_g'), request.form.get('filament_id'),
            request.form.get('machine_id'), request.form.get('layer_height'),
            request.form.get('infill_percent'), request.form.get('wall_count'),
            request.form.get('support_needed'), request.form.get('support_type'),
            request.form.get('base_cost'), request.form.get('suggested_price'),
            request.form.get('profit_margin'), request.form.get('is_public', 1),
            request.form.get('featured', 0), request.form.get('notes'), id))
        conn.commit()
        conn.close()
        flash(t('product_updated'), 'success')
        return redirect(url_for('products'))
    conn.close()
    return render_template('product_form.html', product=product, filaments=filaments, machines=machines)

@app.route('/products/delete/<int:id>')
@login_required
def delete_product(id):
    conn = get_db()
    conn.execute('DELETE FROM products WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    flash(t('deleted'), 'info')
    return redirect(url_for('products'))

@app.route('/orders')
@login_required
def orders():
    conn = get_db()
    all_orders = conn.execute('''SELECT pj.*, p.name as product_name, p.suggested_price, m.name as machine_name, f.name as filament_name FROM print_jobs pj LEFT JOIN products p ON pj.product_id = p.id LEFT JOIN machines m ON pj.machine_id = m.id LEFT JOIN filaments f ON pj.filament_id = f.id ORDER BY pj.created_at DESC''').fetchall()
    conn.close()
    return render_template('orders.html', orders=all_orders)

@app.route('/orders/add', methods=['GET', 'POST'])
@login_required
def add_order():
    conn = get_db()
    products_list = conn.execute('SELECT * FROM products ORDER BY name').fetchall()
    machines_list = conn.execute('SELECT * FROM machines WHERE status != "maintenance"').fetchall()
    filaments_list = conn.execute('SELECT * FROM filaments WHERE status = "available"').fetchall()
    customers_list = conn.execute('SELECT * FROM customers ORDER BY name').fetchall()
    if request.method == 'POST':
        product_id = int(request.form['product_id'])
        machine_id = int(request.form['machine_id'])
        filament_id = int(request.form['filament_id'])
        quantity = int(request.form.get('quantity', 1))
        product = conn.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()
        cost_settings = conn.execute('SELECT * FROM cost_settings WHERE id = 1').fetchone()
        order_number = 'FM' + datetime.now().strftime('%Y%m%d') + str(random.randint(1000, 9999))
        filament = conn.execute('SELECT * FROM filaments WHERE id = ?', (filament_id,)).fetchone()
        filament_cost = (product["filament_weight_g"] * quantity / 1000) * filament["price_per_kg"]
        electricity_cost = product["print_time_hours"] * quantity * 0.3 * cost_settings["electricity_cost_per_kwh"]
        labor_cost = product["print_time_hours"] * quantity * cost_settings["labor_cost_per_hour"]
        depreciation = product["print_time_hours"] * quantity * cost_settings["machine_depreciation_per_hour"]
        maintenance = product["print_time_hours"] * quantity * cost_settings["maintenance_cost_per_hour"]
        total_cost = filament_cost + electricity_cost + labor_cost + depreciation + maintenance
        total_cost = total_cost * (1 + cost_settings["failed_print_rate"] / 100)
        total_cost = total_cost * (1 + cost_settings["overhead_percent"] / 100)
        price_charged = float(request.form['price_charged'])
        profit = price_charged - total_cost
        conn.execute('''INSERT INTO print_jobs (order_number, product_id, customer_name, customer_email, customer_phone, quantity, machine_id, filament_id, status, priority, print_time_estimated, filament_used_g, electricity_cost, labor_cost, total_cost, price_charged, profit, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (
            order_number, product_id, request.form.get('customer_name'),
            request.form.get('customer_email'), request.form.get('customer_phone'),
            quantity, machine_id, filament_id, request.form.get('status', 'pending'),
            request.form.get('priority', 'normal'), product['print_time_hours'] * quantity,
            product['filament_weight_g'] * quantity, round(electricity_cost, 2),
            round(labor_cost, 2), round(total_cost, 2), price_charged, round(profit, 2),
            request.form.get('notes')))
        conn.execute('UPDATE filaments SET weight_remaining_kg = weight_remaining_kg - ? WHERE id = ?', (product['filament_weight_g'] * quantity / 1000, filament_id))
        conn.execute('UPDATE machines SET status = ? WHERE id = ?', ('printing', machine_id))
        conn.commit()
        conn.close()
        flash(t('order_created') + ': ' + order_number, 'success')
        return redirect(url_for('orders'))
    conn.close()
    return render_template('order_form.html', order=None, products=products_list, machines=machines_list, filaments=filaments_list, customers=customers_list)

@app.route('/orders/update-status/<int:id>', methods=['POST'])
@login_required
def update_order_status(id):
    conn = get_db()
    new_status = request.form['status']
    order = conn.execute('SELECT * FROM print_jobs WHERE id = ?', (id,)).fetchone()
    if new_status == 'completed':
        conn.execute('UPDATE print_jobs SET status = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?', (new_status, id))
        conn.execute('UPDATE machines SET status = ? WHERE id = ?', ('idle', order['machine_id']))
    elif new_status == 'cancelled':
        conn.execute('UPDATE filaments SET weight_remaining_kg = weight_remaining_kg + ? WHERE id = ?', (order['filament_used_g'] / 1000, order['filament_id']))
        conn.execute('UPDATE machines SET status = ? WHERE id = ?', ('idle', order['machine_id']))
        conn.execute('UPDATE print_jobs SET status = ? WHERE id = ?', (new_status, id))
    else:
        conn.execute('UPDATE print_jobs SET status = ? WHERE id = ?', (new_status, id))
    conn.commit()
    conn.close()
    flash(t('status_updated'), 'success')
    return redirect(url_for('orders'))

@app.route('/customers')
@login_required
def customers():
    conn = get_db()
    all_customers = conn.execute('SELECT * FROM customers ORDER BY name').fetchall()
    conn.close()
    return render_template('customers.html', customers=all_customers)

@app.route('/customers/add', methods=['GET', 'POST'])
@login_required
def add_customer():
    if request.method == 'POST':
        conn = get_db()
        conn.execute('''INSERT INTO customers (name, email, phone, address, city, state, zip_code, instagram, facebook, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (
            request.form['name'], request.form.get('email'), request.form.get('phone'),
            request.form.get('address'), request.form.get('city'), request.form.get('state'),
            request.form.get('zip_code'), request.form.get('instagram'),
            request.form.get('facebook'), request.form.get('notes')))
        conn.commit()
        conn.close()
        flash(t('customer_created'), 'success')
        return redirect(url_for('customers'))
    return render_template('customer_form.html', customer=None)

@app.route('/marketing')
@login_required
def marketing():
    conn = get_db()
    posts = conn.execute('''SELECT mp.*, p.name as product_name FROM marketing_posts mp LEFT JOIN products p ON mp.product_id = p.id ORDER BY mp.created_at DESC''').fetchall()
    conn.close()
    return render_template('marketing.html', posts=posts)

@app.route('/marketing/generate', methods=['GET', 'POST'])
@login_required
def generate_marketing():
    conn = get_db()
    products_list = conn.execute('SELECT * FROM products WHERE is_public = 1').fetchall()
    if request.method == 'POST':
        product_id = int(request.form['product_id'])
        platform = request.form['platform']
        product = conn.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()
        content = 'New at Filamanager! ' + product['name'] + ' now available!\n\nPrinted with ' + str(product['filament_weight_g']) + 'g of high quality material\nPrint time: ' + str(product['print_time_hours']) + 'h\nStarting at ' + format_currency(product['suggested_price']) + '\n\nOrder now!\n\n#3DPrinting #Maker #' + str(product['category']) + ' #Filamanager'
        hashtags = '#3DPrinting #Maker #Technology #Innovation #Custom #Handmade'
        conn.execute('''INSERT INTO marketing_posts (title, content, platform, product_id, hashtags, status) VALUES (?, ?, ?, ?, ?, ?)''', ('Post ' + platform + ' - ' + product['name'], content, platform, product_id, hashtags, 'draft'))
        conn.commit()
        conn.close()
        flash(t('post_generated'), 'success')
        return redirect(url_for('marketing'))
    conn.close()
    return render_template('marketing_generate.html', products=products_list)

@app.route('/reports')
@login_required
def reports():
    conn = get_db()
    revenue_by_month = conn.execute('''SELECT strftime("%Y-%m", completed_at) as month, COUNT(*) as orders, SUM(price_charged) as revenue, SUM(profit) as profit FROM print_jobs WHERE status = "completed" AND completed_at IS NOT NULL GROUP BY month ORDER BY month DESC LIMIT 6''').fetchall()
    top_products = conn.execute('''SELECT p.name, COUNT(pj.id) as orders, SUM(pj.quantity) as quantity, SUM(pj.price_charged) as revenue FROM print_jobs pj JOIN products p ON pj.product_id = p.id WHERE pj.status = "completed" GROUP BY p.id ORDER BY orders DESC LIMIT 10''').fetchall()
    filament_usage = conn.execute('''SELECT f.material, f.color, SUM(pj.filament_used_g) as total_g FROM print_jobs pj JOIN filaments f ON pj.filament_id = f.id WHERE pj.status = "completed" GROUP BY f.material, f.color ORDER BY total_g DESC''').fetchall()
    machine_usage = conn.execute('''SELECT m.name, COUNT(pj.id) as jobs, SUM(pj.print_time_estimated) as hours FROM print_jobs pj JOIN machines m ON pj.machine_id = m.id WHERE pj.status = "completed" GROUP BY m.id ORDER BY jobs DESC''').fetchall()
    conn.close()
    return render_template('reports.html', revenue_by_month=revenue_by_month, top_products=top_products, filament_usage=filament_usage, machine_usage=machine_usage)

@app.route('/api/product/<int:id>')
@login_required
def api_product(id):
    conn = get_db()
    product = conn.execute('SELECT * FROM products WHERE id = ?', (id,)).fetchone()
    conn.close()
    if product:
        return jsonify(dict(product))
    return jsonify({'error': 'Not found'}), 404

@app.route('/api/filament/<int:id>')
@login_required
def api_filament(id):
    conn = get_db()
    filament = conn.execute('SELECT * FROM filaments WHERE id = ?', (id,)).fetchone()
    conn.close()
    if filament:
        return jsonify(dict(filament))
    return jsonify({'error': 'Not found'}), 404

@app.route('/api/dashboard-stats')
@login_required
def api_dashboard_stats():
    conn = get_db()
    stats = {
        'active_machines': conn.execute("SELECT COUNT(*) as c FROM machines WHERE status = 'printing'").fetchone()['c'],
        'pending_orders': conn.execute("SELECT COUNT(*) as c FROM print_jobs WHERE status = 'pending'").fetchone()['c'],
        'low_stock': conn.execute('SELECT COUNT(*) as c FROM filaments WHERE weight_remaining_kg <= min_stock').fetchone()['c'],
        'month_revenue': conn.execute('''SELECT COALESCE(SUM(price_charged), 0) as total FROM print_jobs WHERE status = "completed" AND strftime("%Y-%m", completed_at) = strftime("%Y-%m", 'now')''').fetchone()['total']
    }
    conn.close()
    return jsonify(stats)

@app.route('/landing')
def landing():
    return render_template('landing.html')


if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
