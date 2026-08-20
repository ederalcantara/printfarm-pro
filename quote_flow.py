import os
import secrets
from functools import wraps

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

quote_flow_bp = Blueprint('quote_flow', __name__)
DATABASE_URL = os.getenv('DATABASE_URL')

SCHEMA = '''
CREATE TABLE IF NOT EXISTS quote_public_links (
 id SERIAL PRIMARY KEY,
 quote_id INTEGER UNIQUE NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
 request_id INTEGER REFERENCES customer_requests(id) ON DELETE SET NULL,
 token VARCHAR(100) UNIQUE NOT NULL,
 client_status VARCHAR(30) NOT NULL DEFAULT 'draft',
 client_message TEXT,
 sent_at TIMESTAMPTZ,
 responded_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
'''


def db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def ensure():
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute(SCHEMA)
        c.commit()
    finally:
        c.close()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped


def get_or_create_link(cur, quote_id):
    cur.execute('SELECT * FROM quote_public_links WHERE quote_id=%s', (quote_id,))
    link = cur.fetchone()
    if link:
        return link
    cur.execute('SELECT notes FROM quotes WHERE id=%s', (quote_id,))
    q = cur.fetchone()
    request_id = None
    if q and q['notes']:
        cur.execute("SELECT id FROM customer_requests WHERE %s LIKE '%%' || request_number || '%%' ORDER BY id DESC LIMIT 1", (q['notes'],))
        r = cur.fetchone()
        if r:
            request_id = r['id']
    token = secrets.token_urlsafe(30)
    cur.execute('INSERT INTO quote_public_links (quote_id,request_id,token) VALUES (%s,%s,%s) RETURNING *', (quote_id, request_id, token))
    return cur.fetchone()


@quote_flow_bp.get('/sales-flow')
@login_required
def sales_flow():
    ensure()
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute('''
                SELECT q.*, c.name AS customer_name, c.email, c.phone,
                       l.token, l.client_status, l.sent_at, l.responded_at
                FROM quotes q
                LEFT JOIN customers c ON c.id=q.customer_id
                LEFT JOIN quote_public_links l ON l.quote_id=q.id
                ORDER BY q.created_at DESC
            ''')
            quotes = cur.fetchall()
    finally:
        c.close()
    return render_template('sales_flow.html', quotes=quotes)


@quote_flow_bp.route('/quotes/<int:quote_id>/prepare', methods=['GET','POST'])
@login_required
def prepare_quote(quote_id):
    ensure()
    c = db()
    try:
        with c.cursor() as cur:
            if request.method == 'POST':
                qty = request.form.get('quantity') or '1'
                unit_price = request.form.get('unit_price') or '0'
                discount = request.form.get('discount') or '0'
                cur.execute('SELECT %s::numeric * %s::numeric AS subtotal', (qty, unit_price))
                subtotal = cur.fetchone()['subtotal']
                cur.execute('SELECT GREATEST(0::numeric, %s::numeric - %s::numeric) AS total', (subtotal, discount))
                total = cur.fetchone()['total']
                cur.execute('UPDATE quotes SET currency=%s, subtotal=%s, discount=%s, total=%s, notes=COALESCE(%s,notes), updated_at=NOW() WHERE id=%s',
                            (request.form.get('currency','USD'), subtotal, discount, total, request.form.get('notes'), quote_id))
                cur.execute('DELETE FROM quote_items WHERE quote_id=%s', (quote_id,))
                cur.execute('INSERT INTO quote_items (quote_id,description,quantity,unit_price) VALUES (%s,%s,%s,%s)',
                            (quote_id, request.form.get('description') or 'Serviço de impressão 3D', qty, unit_price))
                c.commit()
                flash('Orçamento atualizado e pronto para envio.', 'success')
            cur.execute('SELECT q.*, c.name AS customer_name, c.email, c.phone FROM quotes q LEFT JOIN customers c ON c.id=q.customer_id WHERE q.id=%s', (quote_id,))
            q = cur.fetchone()
            if not q:
                return 'Orçamento não encontrado.', 404
            cur.execute('SELECT * FROM quote_items WHERE quote_id=%s ORDER BY id', (quote_id,))
            items = cur.fetchall()
            link = get_or_create_link(cur, quote_id)
            c.commit()
    finally:
        c.close()
    return render_template('prepare_quote.html', q=q, items=items, link=link)


@quote_flow_bp.post('/quotes/<int:quote_id>/send')
@login_required
def send_quote(quote_id):
    ensure()
    c = db()
    try:
        with c.cursor() as cur:
            link = get_or_create_link(cur, quote_id)
            cur.execute("UPDATE quote_public_links SET client_status='sent', sent_at=NOW() WHERE quote_id=%s", (quote_id,))
            cur.execute("UPDATE quotes SET status='awaiting_approval', updated_at=NOW() WHERE id=%s", (quote_id,))
            if link['request_id']:
                cur.execute("UPDATE customer_requests SET status='quoted' WHERE id=%s", (link['request_id'],))
        c.commit()
    finally:
        c.close()
    flash('Orçamento marcado como enviado. Copie o link público e envie ao cliente por WhatsApp, Instagram ou e-mail.', 'success')
    return redirect(url_for('quote_flow.prepare_quote', quote_id=quote_id))


@quote_flow_bp.get('/q/<token>')
def public_quote(token):
    ensure()
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute('''SELECT q.*, c.name AS customer_name, l.client_status, l.client_message
                           FROM quote_public_links l JOIN quotes q ON q.id=l.quote_id
                           LEFT JOIN customers c ON c.id=q.customer_id WHERE l.token=%s''', (token,))
            q = cur.fetchone()
            if q:
                cur.execute('SELECT description,quantity,unit_price FROM quote_items WHERE quote_id=%s ORDER BY id', (q['id'],))
                items = cur.fetchall()
            else:
                items = []
    finally:
        c.close()
    if not q:
        return 'Orçamento não encontrado.', 404
    return render_template('public_quote.html', q=q, items=items, token=token)


@quote_flow_bp.post('/q/<token>/respond')
def public_quote_respond(token):
    action = request.form.get('action')
    message = request.form.get('message','').strip()
    if action not in ('approve','change'):
        return 'Ação inválida.', 400
    ensure()
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT * FROM quote_public_links WHERE token=%s FOR UPDATE', (token,))
            link = cur.fetchone()
            if not link:
                return 'Orçamento não encontrado.', 404
            if action == 'approve':
                cur.execute("UPDATE quote_public_links SET client_status='approved', client_message=%s, responded_at=NOW() WHERE id=%s", (message, link['id']))
                cur.execute("UPDATE quotes SET status='approved', updated_at=NOW() WHERE id=%s", (link['quote_id'],))
                if link['request_id']:
                    cur.execute("UPDATE customer_requests SET status='approved' WHERE id=%s", (link['request_id'],))
            else:
                cur.execute("UPDATE quote_public_links SET client_status='change_requested', client_message=%s, responded_at=NOW() WHERE id=%s", (message, link['id']))
                cur.execute("UPDATE quotes SET status='draft', updated_at=NOW() WHERE id=%s", (link['quote_id'],))
                if link['request_id']:
                    cur.execute("UPDATE customer_requests SET status='waiting_customer', admin_notes=COALESCE(admin_notes,'') || %s WHERE id=%s", ('\nCliente solicitou alteração: ' + message, link['request_id']))
        c.commit()
    finally:
        c.close()
    return redirect(url_for('quote_flow.public_quote', token=token))


@quote_flow_bp.post('/quotes/<int:quote_id>/enter-flow')
@login_required
def enter_flow(quote_id):
    ensure()
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT q.status, l.client_status, l.request_id FROM quotes q LEFT JOIN quote_public_links l ON l.quote_id=q.id WHERE q.id=%s FOR UPDATE', (quote_id,))
            row = cur.fetchone()
            if not row:
                return 'Orçamento não encontrado.', 404
            if row['status'] != 'approved' and row['client_status'] != 'approved':
                flash('O orçamento precisa ser aprovado pelo cliente antes de entrar no fluxo.', 'danger')
                return redirect(url_for('quote_flow.sales_flow'))
            cur.execute("UPDATE quotes SET status='execution', updated_at=NOW() WHERE id=%s", (quote_id,))
            cur.execute("UPDATE projects SET status='execution' WHERE quote_id=%s", (quote_id,))
            if row['request_id']:
                cur.execute("UPDATE customer_requests SET status='production' WHERE id=%s", (row['request_id'],))
        c.commit()
    finally:
        c.close()
    flash('Orçamento aprovado entrou no fluxo de execução.', 'success')
    return redirect(url_for('dashboard', tab='quotes'))
