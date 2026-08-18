import os
from decimal import Decimal

from flask import Flask, jsonify, request
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
DATABASE_URL = os.environ.get('DATABASE_URL')

ALLOWED_TRANSITIONS = {
    'draft': {'awaiting_customer_approval', 'cancelled'},
    'awaiting_customer_approval': {'approved_for_execution', 'cancelled'},
    'approved_for_execution': {'preparing', 'cancelled'},
    'preparing': {'printing', 'cancelled'},
    'printing': {'completed', 'cancelled'},
    'completed': {'delivered'},
    'delivered': set(),
    'cancelled': set(),
}


def get_conn():
    if not DATABASE_URL:
        raise RuntimeError('DATABASE_URL is required')
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def init_db():
    schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
    with open(schema_path, 'r', encoding='utf-8') as f:
        schema = f.read()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(schema)
        conn.commit()
    finally:
        conn.close()


def deduct_inventory_for_quote(conn, quote_id: int):
    """Deduct estimated filament once, atomically, when a quote enters printing."""
    with conn.cursor() as cur:
        cur.execute(
            '''
            SELECT qi.id, qi.filament_id,
                   (qi.estimated_filament_g * qi.quantity) AS total_g,
                   f.weight_remaining_g
            FROM legacy_quote_items qi
            JOIN legacy_filaments f ON f.id = qi.filament_id
            WHERE qi.quote_id = %s
              AND qi.filament_id IS NOT NULL
              AND qi.estimated_filament_g > 0
            FOR UPDATE OF f
            ''',
            (quote_id,),
        )
        rows = cur.fetchall()

        shortages = []
        for row in rows:
            needed = Decimal(row['total_g'])
            remaining = Decimal(row['weight_remaining_g'])
            if remaining < needed:
                shortages.append({
                    'quote_item_id': row['id'],
                    'filament_id': row['filament_id'],
                    'needed_g': float(needed),
                    'remaining_g': float(remaining),
                })

        if shortages:
            return False, shortages

        for row in rows:
            needed = Decimal(row['total_g'])
            cur.execute(
                '''
                INSERT INTO legacy_inventory_movements
                    (filament_id, quote_id, quote_item_id, movement_type, quantity_g, reason)
                VALUES (%s, %s, %s, 'out', %s, 'printing_start')
                ON CONFLICT (quote_item_id, movement_type, reason) DO NOTHING
                RETURNING id
                ''',
                (row['filament_id'], quote_id, row['id'], needed),
            )
            movement = cur.fetchone()
            if movement:
                cur.execute(
                    '''
                    UPDATE legacy_filaments
                    SET weight_remaining_g = weight_remaining_g - %s,
                        updated_at = NOW()
                    WHERE id = %s
                    ''',
                    (needed, row['filament_id']),
                )

    return True, []


@app.get('/health')
def health():
    return jsonify({'ok': True, 'system': 'Legacy System v1'})


@app.post('/api/quotes/<int:quote_id>/status')
def update_quote_status(quote_id):
    payload = request.get_json(silent=True) or {}
    new_status = payload.get('status')
    if not new_status:
        return jsonify({'error': 'status is required'}), 400

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT * FROM legacy_quotes WHERE id = %s FOR UPDATE', (quote_id,))
            quote = cur.fetchone()
            if not quote:
                conn.rollback()
                return jsonify({'error': 'quote not found'}), 404

            current = quote['status']
            if new_status == current:
                conn.rollback()
                return jsonify({'ok': True, 'status': current, 'changed': False})

            if new_status not in ALLOWED_TRANSITIONS.get(current, set()):
                conn.rollback()
                return jsonify({
                    'error': 'invalid status transition',
                    'from': current,
                    'to': new_status,
                }), 409

            if new_status == 'printing':
                ok, shortages = deduct_inventory_for_quote(conn, quote_id)
                if not ok:
                    conn.rollback()
                    return jsonify({
                        'error': 'insufficient inventory',
                        'shortages': shortages,
                    }), 409

            extra = ''
            if new_status == 'approved_for_execution':
                extra = ', customer_approved_at = COALESCE(customer_approved_at, NOW())'
            elif new_status == 'printing':
                extra = ', printing_started_at = COALESCE(printing_started_at, NOW())'
            elif new_status == 'completed':
                extra = ', completed_at = COALESCE(completed_at, NOW())'

            cur.execute(
                f'''UPDATE legacy_quotes
                    SET status = %s, updated_at = NOW() {extra}
                    WHERE id = %s
                    RETURNING *''',
                (new_status, quote_id),
            )
            updated = cur.fetchone()

        conn.commit()
        return jsonify({'ok': True, 'quote': updated})
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.post('/api/filaments')
def create_filament():
    data = request.get_json(silent=True) or {}
    required = ['name', 'material', 'weight_total_g', 'cost_per_kg']
    missing = [k for k in required if data.get(k) in (None, '')]
    if missing:
        return jsonify({'error': 'missing fields', 'fields': missing}), 400

    total = Decimal(str(data['weight_total_g']))
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                '''
                INSERT INTO legacy_filaments
                    (name, brand, material, color, color_hex,
                     weight_total_g, weight_remaining_g, cost_per_kg, currency, min_stock_g)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING *
                ''',
                (
                    data['name'], data.get('brand'), data['material'],
                    data.get('color'), data.get('color_hex'),
                    total, total, Decimal(str(data['cost_per_kg'])),
                    data.get('currency', 'USD'), Decimal(str(data.get('min_stock_g', 100))),
                ),
            )
            row = cur.fetchone()
        conn.commit()
        return jsonify(row), 201
    finally:
        conn.close()


@app.get('/api/filaments')
def list_filaments():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT * FROM legacy_filaments WHERE active = TRUE ORDER BY material, color, name')
            return jsonify(cur.fetchall())
    finally:
        conn.close()


@app.get('/api/quotes/<int:quote_id>/inventory-movements')
def quote_inventory_movements(quote_id):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                '''SELECT * FROM legacy_inventory_movements
                   WHERE quote_id = %s ORDER BY created_at''',
                (quote_id,),
            )
            return jsonify(cur.fetchall())
    finally:
        conn.close()


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
