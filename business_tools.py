import csv
import io
import os
from functools import wraps
from urllib.parse import quote as urlquote

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, Response, flash, redirect, render_template, request, session, url_for

business_tools_bp = Blueprint('business_tools', __name__)
DATABASE_URL = os.getenv('DATABASE_URL')


def db(): return psycopg2.connect(DATABASE_URL,cursor_factory=RealDictCursor)
def ensure(): return
def login_required(view):
    @wraps(view)
    def wrapped(*a,**k):
        if not session.get('user_id'): return redirect(url_for('login'))
        return view(*a,**k)
    return wrapped

def calc_cost(q):
    grams=float(q.get('actual_grams') or q.get('estimated_grams') or 0)
    spool=float(q.get('spool_weight_g') or 0); spool_cost=float(q.get('purchase_cost') or 0)
    material=(grams/spool*spool_cost) if spool else 0
    machine=float(q.get('print_hours') or 0)*float(q.get('hourly_cost') or 0)
    extra=float(q.get('extra_cost') or 0)+float(q.get('labor_cost') or 0)
    return material,machine,extra

@business_tools_bp.route('/business/<int:quote_id>',methods=['GET','POST'])
@login_required
def order_business(quote_id):
    c=db()
    try:
        with c.cursor() as cur:
            if request.method=='POST':
                new_delivery=request.form.get('delivery_status','pending')
                cur.execute('SELECT delivery_status FROM order_business WHERE quote_id=%s FOR UPDATE',(quote_id,));old_business=cur.fetchone();old_delivery=old_business['delivery_status'] if old_business else None
                cur.execute('''INSERT INTO order_business(quote_id,due_date,delivery_method,delivery_address,tracking_code,delivery_status,extra_cost,labor_cost,notes) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(quote_id) DO UPDATE SET due_date=EXCLUDED.due_date,delivery_method=EXCLUDED.delivery_method,delivery_address=EXCLUDED.delivery_address,tracking_code=EXCLUDED.tracking_code,delivery_status=EXCLUDED.delivery_status,extra_cost=EXCLUDED.extra_cost,labor_cost=EXCLUDED.labor_cost,notes=EXCLUDED.notes,updated_at=NOW()''',(quote_id,request.form.get('due_date') or None,request.form.get('delivery_method','pickup'),request.form.get('delivery_address'),request.form.get('tracking_code'),new_delivery,request.form.get('extra_cost') or 0,request.form.get('labor_cost') or 0,request.form.get('notes')))
                if new_delivery=='delivered' and old_delivery!='delivered':
                    cur.execute('SELECT * FROM customer_requests WHERE quote_id=%s FOR UPDATE',(quote_id,));r=cur.fetchone()
                    if r and r.get('product_id') and int(r.get('reserved_stock_qty') or 0)>0:
                        qty=int(r['reserved_stock_qty'])
                        cur.execute('SELECT stock_qty,reserved_stock_qty FROM products WHERE id=%s FOR UPDATE',(r['product_id'],));product=cur.fetchone()
                        if not product or int(product['stock_qty'] or 0)<qty:
                            raise ValueError('Estoque pronto insuficiente para concluir a entrega.')
                        cur.execute('UPDATE products SET stock_qty=stock_qty-%s,reserved_stock_qty=GREATEST(0,reserved_stock_qty-%s) WHERE id=%s',(qty,qty,r['product_id']))
                        cur.execute('UPDATE customer_requests SET reserved_stock_qty=0,status=%s WHERE id=%s',('completed',r['id']))
                        cur.execute("INSERT INTO inventory_movements(product_id,grams,movement_type,reference_type,reference_id,notes,product_qty,filament_g) VALUES(%s,0,'product_sale','quote',%s,'Baixa de estoque pronto na entrega',%s,0)",(r['product_id'],quote_id,-qty))
                        cur.execute("INSERT INTO order_events(request_id,quote_id,event_type,details) VALUES(%s,%s,'delivered',%s)",(r['id'],quote_id,f'{qty} unidade(s) baixadas do estoque pronto'))
                cur.execute("INSERT INTO audit_log(entity_type,entity_id,action,details,user_id) VALUES('quote',%s,'business_updated',%s,%s)",(quote_id,f'entrega={new_delivery}',session.get('user_id')))
                c.commit(); flash('Financeiro, prazo e entrega atualizados.','success')
            cur.execute('''SELECT q.*,c.name customer_name,c.phone,c.email,f.purchase_cost,f.spool_weight_g,m.hourly_cost,b.due_date,b.delivery_method,b.delivery_address,b.tracking_code,b.delivery_status,b.extra_cost,b.labor_cost,b.notes business_notes FROM quotes q LEFT JOIN customers c ON c.id=q.customer_id LEFT JOIN filaments f ON f.id=q.filament_id LEFT JOIN machines m ON m.id=(SELECT machine_id FROM print_jobs WHERE quote_id=q.id ORDER BY id DESC LIMIT 1) LEFT JOIN order_business b ON b.quote_id=q.id WHERE q.id=%s''',(quote_id,)); q=cur.fetchone()
            if not q:return 'Orçamento não encontrado',404
    except ValueError as exc:
        c.rollback();flash(str(exc),'danger');return redirect(url_for('business_tools.order_business',quote_id=quote_id))
    except Exception:
        c.rollback();raise
    finally:c.close()
    material,machine,extra=calc_cost(q); total=float(q['total'] or 0); cost=material+machine+extra; profit=total-cost
    receipt=f"Legacy 3D Studio - Recibo\nOrçamento: {q['quote_number']}\nCliente: {q['customer_name'] or ''}\nValor: ${total:.2f}\nObrigado pela preferência."
    whatsapp='https://wa.me/'+''.join(ch for ch in (q['phone'] or '') if ch.isdigit())+'?text='+urlquote(receipt) if q['phone'] else None
    return render_template('business_order.html',q=q,material=material,machine=machine,extra=extra,cost=cost,profit=profit,receipt=receipt,whatsapp=whatsapp)

@business_tools_bp.get('/business')
@login_required
def business_dashboard():
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('''SELECT q.id,q.quote_number,q.title,q.total,q.currency,q.status,q.estimated_grams,q.actual_grams,q.print_hours,c.name customer_name,f.purchase_cost,f.spool_weight_g,b.due_date,b.delivery_status,b.extra_cost,b.labor_cost FROM quotes q LEFT JOIN customers c ON c.id=q.customer_id LEFT JOIN filaments f ON f.id=q.filament_id LEFT JOIN order_business b ON b.quote_id=q.id ORDER BY q.created_at DESC'''); rows=cur.fetchall()
    finally:c.close()
    for r in rows:
        material,machine,extra=calc_cost(r); r['cost']=material+machine+extra; r['profit']=float(r['total'] or 0)-r['cost']
    return render_template('business_dashboard.html',rows=rows)

@business_tools_bp.get('/backup.csv')
@login_required
def backup_csv():
    c=db();out=io.StringIO();w=csv.writer(out);w.writerow(['quote_number','cliente','projeto','status','valor','moeda','prazo','entrega'])
    try:
        with c.cursor() as cur:
            cur.execute('''SELECT q.quote_number,c.name,q.title,q.status,q.total,q.currency,b.due_date,b.delivery_status FROM quotes q LEFT JOIN customers c ON c.id=q.customer_id LEFT JOIN order_business b ON b.quote_id=q.id ORDER BY q.created_at''')
            for r in cur.fetchall():w.writerow(list(r.values()))
    finally:c.close()
    return Response(out.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=legacy-backup-orcamentos.csv'})
