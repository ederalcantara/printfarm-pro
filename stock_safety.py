import os
import re
from decimal import Decimal, InvalidOperation
from functools import wraps

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

stock_safety_bp = Blueprint('stock_safety', __name__)
DATABASE_URL = os.getenv('DATABASE_URL')
MIN_VALID_GRAMS_PER_UNIT = Decimal('1.00')


def db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def d(value, default='0'):
    try:
        return Decimal(str(value if value not in (None, '') else default))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped


@stock_safety_bp.before_app_request
def stock_guardrails():
    if request.method == 'GET' and request.path == '/' and request.args.get('tab') == 'stock':
        return redirect(url_for('stock_safety.stock_admin'))

    if request.method == 'POST' and request.path == '/production/stock/create':
        product_id = request.form.get('product_id')
        c = db()
        try:
            with c.cursor() as cur:
                cur.execute('SELECT id,name,grams_per_unit FROM products WHERE id=%s', (product_id,))
                product = cur.fetchone()
        finally:
            c.close()
        if not product:
            return None
        grams = d(request.form.get('grams_per_unit'), product['grams_per_unit'] or 0)
        if grams <= 0:
            flash(f"{product['name']}: cadastre o peso em g/unidade antes de produzir.", 'danger')
            return redirect(url_for('operations.stock_production'))
        if grams < MIN_VALID_GRAMS_PER_UNIT:
            flash(f"{product['name']}: {grams} g/unidade parece incorreto. A produção foi bloqueada. Confira o peso real do produto (mínimo de segurança: 1,00 g).", 'danger')
            return redirect(url_for('operations.stock_production'))

    if request.method == 'POST' and re.fullmatch(r'/production/stock/\d+/complete', request.path):
        raw = request.form.get('actual_grams')
        if raw not in (None, ''):
            actual = d(raw)
            if actual < MIN_VALID_GRAMS_PER_UNIT:
                flash('Consumo real abaixo de 1,00 g foi bloqueado. Confira o valor antes de concluir o lote.', 'danger')
                return redirect(url_for('operations.stock_production'))
    return None


@stock_safety_bp.get('/stock-admin')
@login_required
def stock_admin():
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute('''SELECT id,brand,material,color,remaining_g,reserved_g,min_g,purchase_cost,currency,location,
                                  GREATEST(remaining_g-reserved_g,0) AS available_g
                           FROM filaments ORDER BY material,color,brand''')
            filaments = cur.fetchall()
            cur.execute('''SELECT im.*,f.material,f.color FROM inventory_movements im
                           JOIN filaments f ON f.id=im.filament_id
                           ORDER BY im.created_at DESC LIMIT 100''')
            movements = cur.fetchall()
    finally:
        c.close()
    return render_template('stock_admin.html', filaments=filaments, movements=movements)


@stock_safety_bp.post('/stock-admin/<int:filament_id>/adjust')
@login_required
def adjust_stock(filament_id):
    grams = d(request.form.get('grams'))
    if grams == 0:
        flash('O ajuste não pode ser zero.', 'warning')
        return redirect(url_for('stock_safety.stock_admin'))
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT * FROM filaments WHERE id=%s FOR UPDATE', (filament_id,))
            filament = cur.fetchone()
            if not filament:
                flash('Filamento não encontrado.', 'danger')
                return redirect(url_for('stock_safety.stock_admin'))
            remaining = d(filament['remaining_g'])
            reserved = d(filament['reserved_g'])
            new_remaining = remaining + grams
            if new_remaining < 0:
                flash('O ajuste deixaria o estoque físico negativo.', 'danger')
                return redirect(url_for('stock_safety.stock_admin'))
            if new_remaining < reserved:
                flash(f'Ajuste bloqueado: existem {reserved} g reservados e o estoque físico ficaria em {new_remaining} g.', 'danger')
                return redirect(url_for('stock_safety.stock_admin'))
            cur.execute('UPDATE filaments SET remaining_g=%s WHERE id=%s', (new_remaining, filament_id))
            cur.execute('''INSERT INTO inventory_movements(filament_id,grams,movement_type,reference_type,reference_id,notes)
                           VALUES(%s,%s,'manual_adjustment','filament',%s,%s)''',
                        (filament_id, grams, filament_id, request.form.get('notes') or 'Ajuste manual'))
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
    flash('Estoque ajustado com segurança.', 'success')
    return redirect(url_for('stock_safety.stock_admin'))
