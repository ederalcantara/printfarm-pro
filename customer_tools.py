import os
from functools import wraps
from urllib.parse import quote as urlquote

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, flash, redirect, render_template, session, url_for

from app import next_quote_number

customer_tools_bp = Blueprint('customer_tools', __name__)
DATABASE_URL = os.getenv('DATABASE_URL')


def db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped


@customer_tools_bp.get('/customers/<int:customer_id>/history')
@login_required
def customer_history(customer_id):
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT * FROM customers WHERE id=%s', (customer_id,))
            customer = cur.fetchone()
            if not customer:
                return 'Cliente não encontrado.', 404
            cur.execute('''
                SELECT q.*, p.status AS payment_status, p.amount_paid,
                       b.delivery_status, b.due_date
                FROM quotes q
                LEFT JOIN quote_payments p ON p.quote_id=q.id
                LEFT JOIN order_business b ON b.quote_id=q.id
                WHERE q.customer_id=%s
                ORDER BY q.created_at DESC
            ''', (customer_id,))
            quotes = cur.fetchall()
            cur.execute("SELECT COUNT(*) AS orders, COALESCE(SUM(total),0) AS spent FROM quotes WHERE customer_id=%s AND status NOT IN ('canceled')", (customer_id,))
            stats = cur.fetchone()
    finally:
        c.close()
    phone = ''.join(ch for ch in (customer['phone'] or '') if ch.isdigit())
    followup = f"Olá {customer['name']}! Aqui é a Legacy 3D Studio. Obrigado por escolher nosso trabalho. Como ficou sua experiência com o pedido? Se puder, envie uma avaliação ou uma foto da peça em uso. Será um prazer atender você novamente!"
    followup_url = 'https://wa.me/' + phone + '?text=' + urlquote(followup) if phone else None
    return render_template('customer_history.html', customer=customer, quotes=quotes, stats=stats, followup=followup, followup_url=followup_url)


@customer_tools_bp.post('/quotes/<int:quote_id>/repeat')
@login_required
def repeat_quote(quote_id):
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT * FROM quotes WHERE id=%s', (quote_id,))
            old = cur.fetchone()
            if not old:
                return 'Orçamento não encontrado.', 404
            cur.execute('SELECT * FROM quote_items WHERE quote_id=%s ORDER BY id LIMIT 1', (quote_id,))
            item = cur.fetchone()
            number = next_quote_number(cur)
            cur.execute('''
                INSERT INTO quotes
                (quote_number,customer_id,title,project_type,status,currency,subtotal,discount,total,filament_id,estimated_grams,print_hours,notes)
                VALUES (%s,%s,%s,%s,'draft',%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
            ''', (number, old['customer_id'], old['title'], old['project_type'], old['currency'], old['subtotal'], old['discount'], old['total'], old['filament_id'], old['estimated_grams'], old['print_hours'], 'Pedido repetido a partir de ' + old['quote_number']))
            new_id = cur.fetchone()['id']
            if item:
                cur.execute('INSERT INTO quote_items (quote_id,description,quantity,unit_price) VALUES (%s,%s,%s,%s)', (new_id, item['description'], item['quantity'], item['unit_price']))
            cur.execute("INSERT INTO projects (quote_id,customer_id,project_type,name,status,description) VALUES (%s,%s,%s,%s,'development',%s)", (new_id, old['customer_id'], old['project_type'], old['title'], 'Pedido repetido a partir de ' + old['quote_number']))
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
    flash(f'Novo orçamento {number} criado a partir do pedido anterior. Revise antes de enviar ao cliente.', 'success')
    return redirect(url_for('quote_flow.prepare_quote', quote_id=new_id))
