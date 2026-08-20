import os
from datetime import datetime
from functools import wraps
from io import BytesIO

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, flash, redirect, render_template, request, send_file, session, url_for

online_bp = Blueprint('online', __name__)
DATABASE_URL = os.getenv('DATABASE_URL')

STATUS_LABELS = {
    'received': 'Recebido',
    'reviewing': 'Em análise',
    'waiting_customer': 'Aguardando cliente',
    'quoted': 'Orçamento enviado',
    'approved': 'Aprovado',
    'rejected': 'Não aprovado',
    'production': 'Em produção',
    'completed': 'Concluído',
}


def db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped


@online_bp.get('/online-requests')
@login_required
def list_requests():
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute('''
                SELECT r.*,
                       (SELECT COUNT(*) FROM customer_request_files f WHERE f.request_id=r.id) AS file_count
                FROM customer_requests r
                ORDER BY r.created_at DESC
            ''')
            items = cur.fetchall()
    finally:
        c.close()
    return render_template('online_requests.html', items=items, status_labels=STATUS_LABELS)


@online_bp.get('/online-requests/<int:request_id>')
@login_required
def request_detail(request_id):
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT * FROM customer_requests WHERE id=%s', (request_id,))
            item = cur.fetchone()
            cur.execute('SELECT id,file_name,file_size,content_type,created_at FROM customer_request_files WHERE request_id=%s ORDER BY created_at', (request_id,))
            files = cur.fetchall()
    finally:
        c.close()
    if not item:
        return 'Pedido não encontrado.', 404
    return render_template('online_request_detail.html', item=item, files=files, status_labels=STATUS_LABELS)


@online_bp.post('/online-requests/<int:request_id>/status')
@login_required
def update_status(request_id):
    status = request.form.get('status', 'received')
    if status not in STATUS_LABELS:
        flash('Status inválido.', 'danger')
        return redirect(url_for('online.request_detail', request_id=request_id))
    notes = request.form.get('admin_notes', '').strip()
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute('UPDATE customer_requests SET status=%s, admin_notes=%s WHERE id=%s', (status, notes, request_id))
        c.commit()
    finally:
        c.close()
    flash('Pedido atualizado.', 'success')
    return redirect(url_for('online.request_detail', request_id=request_id))


@online_bp.get('/online-request-files/<int:file_id>/download')
@login_required
def download_request_file(file_id):
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT * FROM customer_request_files WHERE id=%s', (file_id,))
            f = cur.fetchone()
    finally:
        c.close()
    if not f:
        return 'Arquivo não encontrado.', 404
    return send_file(BytesIO(f['file_data']), mimetype=f['content_type'] or 'application/octet-stream', as_attachment=True, download_name=f['file_name'])


@online_bp.post('/online-requests/<int:request_id>/convert')
@login_required
def convert_to_quote(request_id):
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT * FROM customer_requests WHERE id=%s FOR UPDATE', (request_id,))
            r = cur.fetchone()
            if not r:
                return 'Pedido não encontrado.', 404

            # Reuse an existing customer by email/phone when possible; otherwise create one.
            customer = None
            if r['email']:
                cur.execute('SELECT * FROM customers WHERE lower(email)=lower(%s) ORDER BY id LIMIT 1', (r['email'],))
                customer = cur.fetchone()
            if not customer and r['phone']:
                cur.execute('SELECT * FROM customers WHERE phone=%s ORDER BY id LIMIT 1', (r['phone'],))
                customer = cur.fetchone()
            if not customer:
                cur.execute('INSERT INTO customers (name,phone,email,notes) VALUES (%s,%s,%s,%s) RETURNING *',
                            (r['name'], r['phone'], r['email'], 'Criado a partir do pedido online ' + r['request_number']))
                customer = cur.fetchone()

            number = 'LEG-' + datetime.now().strftime('%Y%m%d-%H%M%S')
            notes = 'Pedido online: %s\nTipo: %s\nUso: %s\nMaterial preferido: %s\nCor preferida: %s\nPrazo: %s\n\n%s' % (
                r['request_number'], r['request_type'], r['intended_use'] or '-', r['preferred_material'] or '-',
                r['preferred_color'] or '-', r['deadline'] or '-', r['description'])
            cur.execute('''
                INSERT INTO quotes (quote_number,customer_id,title,project_type,status,currency,subtotal,discount,total,estimated_grams,print_hours,notes)
                VALUES (%s,%s,%s,'customer','draft','USD',0,0,0,0,0,%s)
                RETURNING id
            ''', (number, customer['id'], r['title'], notes))
            quote_id = cur.fetchone()['id']
            cur.execute('UPDATE customer_requests SET status=%s, admin_notes=COALESCE(admin_notes,\'\') || %s WHERE id=%s',
                        ('reviewing', '\nConvertido para orçamento ' + number, request_id))
        c.commit()
    finally:
        c.close()
    flash('Pedido transformado em orçamento. Agora você pode definir preço, material e produção.', 'success')
    return redirect(url_for('dashboard', tab='quotes'))
