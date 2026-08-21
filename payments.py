import os
import secrets
from decimal import Decimal, InvalidOperation
from functools import wraps

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

payments_bp = Blueprint('payments', __name__)
DATABASE_URL = os.getenv('DATABASE_URL')

VENMO_PAYLOAD = 'https://venmo.com/code?user_id=3791804503688716942&created=1787270062.608913'
ZELLE_PAYLOAD = 'https://enroll.zellepay.com/qr-codes?data=eyJuYW1lIjoiRURFUiIsImFjdGlvbiI6InBheW1lbnQiLCJ0b2tlbiI6IjUwODM3MjUxNDIifQ=='

SCHEMA = '''
CREATE TABLE IF NOT EXISTS quote_payments (
 id SERIAL PRIMARY KEY,
 quote_id INTEGER UNIQUE NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
 token VARCHAR(100) UNIQUE NOT NULL,
 payment_type VARCHAR(20) NOT NULL DEFAULT 'full',
 amount_due NUMERIC(12,2) NOT NULL DEFAULT 0,
 amount_paid NUMERIC(12,2) NOT NULL DEFAULT 0,
 method VARCHAR(20),
 status VARCHAR(30) NOT NULL DEFAULT 'not_requested',
 client_note TEXT,
 client_reported_at TIMESTAMPTZ,
 confirmed_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
'''

def db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def ensure_payment_schema():
    c=db()
    try:
        with c.cursor() as cur: cur.execute(SCHEMA)
        c.commit()
    finally: c.close()

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped

def number(value, default='0'):
    try: return Decimal(str(value if value not in (None,'') else default))
    except (InvalidOperation, ValueError, TypeError): return Decimal(default)

def get_or_create(cur, quote_id):
    cur.execute('SELECT * FROM quote_payments WHERE quote_id=%s',(quote_id,))
    p=cur.fetchone()
    if p: return p
    cur.execute('SELECT total FROM quotes WHERE id=%s',(quote_id,)); q=cur.fetchone()
    if not q: return None
    cur.execute('INSERT INTO quote_payments (quote_id,token,amount_due) VALUES (%s,%s,%s) RETURNING *',(quote_id,secrets.token_urlsafe(32),q['total']))
    return cur.fetchone()

@payments_bp.route('/quotes/<int:quote_id>/payment', methods=['GET','POST'])
@login_required
def admin_payment(quote_id):
    ensure_payment_schema(); c=db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT q.*,c.name AS customer_name,c.email,c.phone FROM quotes q LEFT JOIN customers c ON c.id=q.customer_id WHERE q.id=%s',(quote_id,)); q=cur.fetchone()
            if not q: return 'Orçamento não encontrado.',404
            p=get_or_create(cur,quote_id); c.commit()
            if request.method=='POST':
                action=request.form.get('action','save')
                if action=='save':
                    payment_type=request.form.get('payment_type','full')
                    amount_due=number(request.form.get('amount_due'), q['total'])
                    method=request.form.get('method') or None
                    if payment_type not in ('full','deposit'): payment_type='full'
                    if method not in ('zelle','venmo','both'): method=None
                    if amount_due <= 0:
                        flash('Informe um valor de pagamento maior que zero.','danger')
                    else:
                        cur.execute("UPDATE quote_payments SET payment_type=%s,amount_due=%s,method=%s,status='awaiting_payment',updated_at=NOW() WHERE quote_id=%s",(payment_type,amount_due,method,quote_id)); c.commit(); flash('Pagamento liberado para este orçamento.','success')
                elif action=='confirm':
                    paid=number(request.form.get('amount_paid'), p['amount_due'])
                    if paid < 0: paid=Decimal('0')
                    new_status='paid' if paid >= number(p['amount_due']) else 'deposit_paid'
                    cur.execute("UPDATE quote_payments SET amount_paid=%s,status=%s,confirmed_at=NOW(),updated_at=NOW() WHERE quote_id=%s",(paid,new_status,quote_id)); c.commit(); flash('Recebimento confirmado.','success')
                elif action=='reset':
                    cur.execute("UPDATE quote_payments SET amount_paid=0,status='awaiting_payment',client_note=NULL,client_reported_at=NULL,confirmed_at=NULL,updated_at=NOW() WHERE quote_id=%s",(quote_id,)); c.commit(); flash('Status de pagamento redefinido.','success')
                return redirect(url_for('payments.admin_payment',quote_id=quote_id))
            cur.execute('SELECT * FROM quote_payments WHERE quote_id=%s',(quote_id,)); p=cur.fetchone()
    finally: c.close()
    public_url=request.url_root.rstrip('/')+url_for('payments.public_payment',token=p['token'])
    return render_template('admin_payment.html',q=q,p=p,public_url=public_url)

@payments_bp.get('/pay/<token>')
def public_payment(token):
    ensure_payment_schema(); c=db()
    try:
        with c.cursor() as cur:
            cur.execute('''SELECT p.*,q.quote_number,q.title,q.currency,q.total,c.name AS customer_name FROM quote_payments p JOIN quotes q ON q.id=p.quote_id LEFT JOIN customers c ON c.id=q.customer_id WHERE p.token=%s''',(token,)); p=cur.fetchone()
    finally:c.close()
    if not p:return 'Pagamento não encontrado.',404
    if p['status']=='not_requested': return 'Pagamento ainda não foi liberado para este pedido.',403
    payloads=[]
    if p['method'] in ('venmo','both'): payloads.append({'name':'Venmo','key':'venmo','payload':VENMO_PAYLOAD})
    if p['method'] in ('zelle','both'): payloads.append({'name':'Zelle','key':'zelle','payload':ZELLE_PAYLOAD})
    balance=max(number(p['amount_due'])-number(p['amount_paid']),Decimal('0'))
    return render_template('public_payment.html',p=p,payloads=payloads,balance=balance,token=token)

@payments_bp.post('/pay/<token>/reported')
def client_reported(token):
    ensure_payment_schema(); note=request.form.get('note','').strip(); method=request.form.get('method','').strip().lower()
    if method not in ('zelle','venmo'): method=None
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT * FROM quote_payments WHERE token=%s FOR UPDATE',(token,)); p=cur.fetchone()
            if not p:return 'Pagamento não encontrado.',404
            if p['status'] in ('paid','deposit_paid'):
                return redirect(url_for('payments.public_payment',token=token))
            cur.execute("UPDATE quote_payments SET status='pending_confirmation',method=COALESCE(%s,method),client_note=%s,client_reported_at=NOW(),updated_at=NOW() WHERE id=%s",(method,note,p['id']))
        c.commit()
    finally:c.close()
    return redirect(url_for('payments.public_payment',token=token))
