import os
from functools import wraps
from urllib.parse import quote as urlquote

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app import next_quote_number

customer_tools_bp = Blueprint('customer_tools', __name__)
DATABASE_URL = os.getenv('DATABASE_URL')


def db():return psycopg2.connect(DATABASE_URL,cursor_factory=RealDictCursor)
def login_required(view):
    @wraps(view)
    def wrapped(*args,**kwargs):
        if not session.get('user_id'):return redirect(url_for('login'))
        return view(*args,**kwargs)
    return wrapped

@customer_tools_bp.get('/customers/<int:customer_id>/history')
@login_required
def customer_history(customer_id):
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT * FROM customers WHERE id=%s',(customer_id,));customer=cur.fetchone()
            if not customer:return 'Cliente não encontrado.',404
            cur.execute('''SELECT q.*,p.status AS payment_status,p.amount_paid,b.delivery_status,b.due_date
                           FROM quotes q LEFT JOIN quote_payments p ON p.quote_id=q.id LEFT JOIN order_business b ON b.quote_id=q.id
                           WHERE q.customer_id=%s ORDER BY q.created_at DESC''',(customer_id,));quotes=cur.fetchall()
            cur.execute("SELECT COUNT(*) AS orders,COALESCE(SUM(total),0) AS spent,MAX(created_at) AS last_order FROM quotes WHERE customer_id=%s AND status NOT IN ('canceled')",(customer_id,));stats=cur.fetchone()
            cur.execute('''SELECT DISTINCT qi.description FROM quote_items qi JOIN quotes q ON q.id=qi.quote_id
                           WHERE q.customer_id=%s ORDER BY qi.description LIMIT 20''',(customer_id,));products=cur.fetchall()
    finally:c.close()
    phone=''.join(ch for ch in (customer['phone'] or '') if ch.isdigit())
    followup=f"Olá {customer['name']}! Aqui é a Legacy 3D Studio. Obrigado por escolher nosso trabalho. Como ficou sua experiência com o pedido? Se puder, envie uma avaliação ou uma foto da peça em uso. Será um prazer atender você novamente!"
    followup_url='https://wa.me/'+phone+'?text='+urlquote(followup) if phone else None
    return render_template('customer_history.html',customer=customer,quotes=quotes,stats=stats,products=products,followup=followup,followup_url=followup_url)

@customer_tools_bp.get('/customers/deduplicate')
@login_required
def deduplicate_customers():
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('''SELECT array_agg(id ORDER BY id) AS ids,array_agg(name ORDER BY id) AS names,
                                  max(email) AS email,max(phone) AS phone,count(*) AS n
                           FROM customers
                           GROUP BY COALESCE(NULLIF(lower(trim(email)),''),NULLIF(regexp_replace(COALESCE(phone,''),'[^0-9]','','g'),''))
                           HAVING count(*)>1 AND COALESCE(NULLIF(lower(trim(max(email))),''),NULLIF(regexp_replace(COALESCE(max(phone),''),'[^0-9]','','g'),'')) IS NOT NULL
                           ORDER BY count(*) DESC''');groups=cur.fetchall()
    finally:c.close()
    return render_template('customer_dedupe.html',groups=groups)

@customer_tools_bp.post('/customers/deduplicate/merge')
@login_required
def merge_customers():
    keep_id=int(request.form.get('keep_id') or 0);duplicate_id=int(request.form.get('duplicate_id') or 0)
    if not keep_id or not duplicate_id or keep_id==duplicate_id:
        flash('Escolha dois cadastros diferentes.','danger');return redirect(url_for('customer_tools.deduplicate_customers'))
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT * FROM customers WHERE id IN (%s,%s) FOR UPDATE',(keep_id,duplicate_id));rows=cur.fetchall()
            if len(rows)!=2:
                flash('Cliente não encontrado.','danger');return redirect(url_for('customer_tools.deduplicate_customers'))
            cur.execute('UPDATE quotes SET customer_id=%s WHERE customer_id=%s',(keep_id,duplicate_id))
            cur.execute('UPDATE projects SET customer_id=%s WHERE customer_id=%s',(keep_id,duplicate_id))
            cur.execute('UPDATE customer_requests SET customer_id=%s WHERE customer_id=%s',(keep_id,duplicate_id))
            cur.execute('''UPDATE customers k SET phone=COALESCE(NULLIF(k.phone,''),d.phone),email=COALESCE(NULLIF(k.email,''),d.email),
                           address=COALESCE(NULLIF(k.address,''),d.address),notes=concat_ws(E'\n',NULLIF(k.notes,''),NULLIF(d.notes,''))
                           FROM customers d WHERE k.id=%s AND d.id=%s''',(keep_id,duplicate_id))
            cur.execute('DELETE FROM customers WHERE id=%s',(duplicate_id,))
        c.commit()
    except Exception:c.rollback();raise
    finally:c.close()
    flash('Cadastros unidos; pedidos e projetos foram preservados.','success')
    return redirect(url_for('customer_tools.deduplicate_customers'))

@customer_tools_bp.post('/quotes/<int:quote_id>/repeat')
@login_required
def repeat_quote(quote_id):
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT * FROM quotes WHERE id=%s',(quote_id,));old=cur.fetchone()
            if not old:return 'Orçamento não encontrado.',404
            cur.execute('SELECT * FROM quote_items WHERE quote_id=%s ORDER BY id LIMIT 1',(quote_id,));item=cur.fetchone();number=next_quote_number(cur)
            cur.execute('''INSERT INTO quotes(quote_number,customer_id,title,project_type,status,currency,subtotal,discount,total,filament_id,estimated_grams,print_hours,notes)
                           VALUES(%s,%s,%s,%s,'draft',%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',(number,old['customer_id'],old['title'],old['project_type'],old['currency'],old['subtotal'],old['discount'],old['total'],old['filament_id'],old['estimated_grams'],old['print_hours'],'Pedido repetido a partir de '+old['quote_number']));new_id=cur.fetchone()['id']
            if item:cur.execute('INSERT INTO quote_items(quote_id,description,quantity,unit_price,product_id) VALUES(%s,%s,%s,%s,%s)',(new_id,item['description'],item['quantity'],item['unit_price'],item.get('product_id')))
            cur.execute("INSERT INTO projects(quote_id,customer_id,project_type,name,status,description) VALUES(%s,%s,%s,%s,'development',%s)",(new_id,old['customer_id'],old['project_type'],old['title'],'Pedido repetido a partir de '+old['quote_number']))
        c.commit()
    except Exception:c.rollback();raise
    finally:c.close()
    flash(f'Novo orçamento {number} criado. Revise antes de enviar.','success')
    return redirect(url_for('quote_flow.prepare_quote',quote_id=new_id))
