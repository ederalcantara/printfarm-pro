import os
import re
from datetime import datetime
from functools import wraps
from io import BytesIO

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, flash, redirect, render_template, request, send_file, session, url_for

online_bp = Blueprint('online', __name__)
DATABASE_URL = os.getenv('DATABASE_URL')

STATUS_LABELS = {'received':'Recebido','reviewing':'Em análise','waiting_customer':'Aguardando cliente','quoted':'Orçamento enviado','approved':'Aprovado','rejected':'Não aprovado','production':'Em produção','completed':'Concluído'}


def db():return psycopg2.connect(DATABASE_URL,cursor_factory=RealDictCursor)
def norm_phone(value):return re.sub(r'\D','',value or '')
def login_required(view):
    @wraps(view)
    def wrapped(*args,**kwargs):
        if not session.get('user_id'):return redirect(url_for('login'))
        return view(*args,**kwargs)
    return wrapped

@online_bp.get('/online-requests')
@login_required
def list_requests():
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('''SELECT r.*,(SELECT COUNT(*) FROM customer_request_files f WHERE f.request_id=r.id) AS file_count
                           FROM customer_requests r ORDER BY r.created_at DESC''');items=cur.fetchall()
    finally:c.close()
    return render_template('online_requests.html',items=items,status_labels=STATUS_LABELS)

@online_bp.get('/online-requests/<int:request_id>')
@login_required
def request_detail(request_id):
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT * FROM customer_requests WHERE id=%s',(request_id,));item=cur.fetchone()
            cur.execute('SELECT id,file_name,file_size,content_type,created_at FROM customer_request_files WHERE request_id=%s ORDER BY created_at',(request_id,));files=cur.fetchall()
    finally:c.close()
    if not item:return 'Pedido não encontrado.',404
    return render_template('online_request_detail.html',item=item,files=files,status_labels=STATUS_LABELS)

@online_bp.post('/online-requests/<int:request_id>/status')
@login_required
def update_status(request_id):
    status=request.form.get('status','received')
    if status not in STATUS_LABELS:
        flash('Status inválido.','danger');return redirect(url_for('online.request_detail',request_id=request_id))
    notes=request.form.get('admin_notes','').strip();c=db()
    try:
        with c.cursor() as cur:
            cur.execute('UPDATE customer_requests SET status=%s,admin_notes=%s WHERE id=%s',(status,notes,request_id))
            cur.execute("INSERT INTO order_events(request_id,event_type,details) VALUES(%s,'status_changed',%s)",(request_id,status))
        c.commit()
    finally:c.close()
    flash('Pedido atualizado.','success');return redirect(url_for('online.request_detail',request_id=request_id))

@online_bp.get('/online-request-files/<int:file_id>/download')
@login_required
def download_request_file(file_id):
    c=db()
    try:
        with c.cursor() as cur:cur.execute('SELECT * FROM customer_request_files WHERE id=%s',(file_id,));f=cur.fetchone()
    finally:c.close()
    if not f:return 'Arquivo não encontrado.',404
    return send_file(BytesIO(f['file_data']),mimetype=f['content_type'] or 'application/octet-stream',as_attachment=True,download_name=f['file_name'])

@online_bp.post('/online-requests/<int:request_id>/convert')
@login_required
def convert_to_quote(request_id):
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT * FROM customer_requests WHERE id=%s FOR UPDATE',(request_id,));r=cur.fetchone()
            if not r:return 'Pedido não encontrado.',404
            if r.get('quote_id'):
                flash('Este pedido já possui orçamento vinculado.','warning');return redirect(url_for('operations.order_detail',request_id=request_id))

            customer=None
            if r['email']:
                cur.execute('SELECT * FROM customers WHERE lower(trim(email))=lower(trim(%s)) ORDER BY id LIMIT 1',(r['email'],));customer=cur.fetchone()
            phone=norm_phone(r['phone'])
            if not customer and phone:
                cur.execute("SELECT * FROM customers WHERE regexp_replace(COALESCE(phone,''),'[^0-9]','','g')=%s ORDER BY id LIMIT 1",(phone,));customer=cur.fetchone()
            if not customer:
                cur.execute('INSERT INTO customers(name,phone,email,notes) VALUES(%s,%s,%s,%s) RETURNING *',(r['name'],r['phone'],r['email'],'Criado a partir do pedido '+r['request_number']));customer=cur.fetchone()

            number='LEG-'+datetime.now().strftime('%Y%m%d-%H%M%S')
            currency=r.get('currency') or 'USD';subtotal=r.get('total_amount') or 0
            notes='Pedido online: %s\nOrigem: %s\nPrazo: %s\n\n%s' % (r['request_number'],r.get('source') or '—',r['deadline'] or '-',r['description'])
            cur.execute('''INSERT INTO quotes(quote_number,customer_id,title,project_type,status,currency,subtotal,discount,total,estimated_grams,print_hours,notes)
                           VALUES(%s,%s,%s,'customer','draft',%s,%s,0,%s,0,0,%s) RETURNING id''',(number,customer['id'],r['title'],currency,subtotal,subtotal,notes));quote_id=cur.fetchone()['id']
            cur.execute("INSERT INTO quote_items(quote_id,description,quantity,unit_price,product_id) VALUES(%s,%s,%s,%s,%s)",(quote_id,r['title'],r['quantity'],r.get('unit_price') or 0,r.get('product_id')))
            cur.execute("INSERT INTO projects(quote_id,customer_id,project_type,name,status,description) VALUES(%s,%s,'customer',%s,'development',%s)",(quote_id,customer['id'],r['title'],r['description']))
            cur.execute("UPDATE customer_requests SET status='reviewing',customer_id=%s,quote_id=%s,admin_notes=COALESCE(admin_notes,'') || %s WHERE id=%s",(customer['id'],quote_id,'\nConvertido para orçamento '+number,request_id))
            cur.execute("INSERT INTO order_events(request_id,quote_id,event_type,details) VALUES(%s,%s,'quote_created',%s)",(request_id,quote_id,number))
        c.commit()
    except Exception:c.rollback();raise
    finally:c.close()
    flash('Pedido transformado em orçamento e vinculado ao cliente.','success')
    return redirect(url_for('operations.order_detail',request_id=request_id))
