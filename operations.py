import os
from decimal import Decimal, InvalidOperation
from functools import wraps

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

import customer_portal

# customer_portal historically altered tables on every public request. Migrations now own schema changes.
customer_portal.ensure = lambda: None

operations_bp = Blueprint('operations', __name__)
DATABASE_URL = os.getenv('DATABASE_URL')


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


@operations_bp.before_app_request
def protect_public_catalog_stock():
    """Track campaign source and reserve finished stock around the legacy public portal."""
    if request.path != '/request-quote':
        return None
    if request.method == 'GET':
        session['_legacy_order_source'] = {
            'source': (request.args.get('source') or request.args.get('utm_source') or 'catalog')[:40],
            'utm_source': (request.args.get('utm_source') or '')[:120],
            'utm_medium': (request.args.get('utm_medium') or '')[:120],
            'utm_campaign': (request.args.get('utm_campaign') or '')[:180],
        }
        return None
    if request.method != 'POST':
        return None

    meta = session.get('_legacy_order_source') or {'source':'catalog','utm_source':'','utm_medium':'','utm_campaign':''}
    g.legacy_order_meta = meta
    g.legacy_stock_reservation = None
    if request.form.get('mode') != 'catalog':
        return None
    product_id = request.form.get('product_id')
    try:
        quantity = max(int(request.form.get('quantity') or 1), 1)
    except ValueError:
        quantity = 1
    if not product_id:
        return None

    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('''SELECT id,name,stock_qty,reserved_stock_qty,fulfillment_mode
                           FROM products WHERE id=%s AND active=TRUE FOR UPDATE''',(product_id,))
            product=cur.fetchone()
            if not product:
                return None
            available=max(int(product['stock_qty'] or 0)-int(product['reserved_stock_qty'] or 0),0)
            reserve=0
            if product['fulfillment_mode']=='ready_stock':
                if quantity>available:
                    flash(f"{product['name']}: há somente {available} unidade(s) disponível(is) para pronta entrega.",'warning')
                    return redirect(url_for('portal.request_quote',product=product_id)+'#catalogo')
                reserve=quantity
            elif product['fulfillment_mode']=='both':
                reserve=min(quantity,available)
            if reserve:
                cur.execute('UPDATE products SET reserved_stock_qty=reserved_stock_qty+%s WHERE id=%s',(reserve,product_id))
            c.commit()
            g.legacy_stock_reservation={'product_id':int(product_id),'qty':reserve,'requested_qty':quantity}
    except Exception:
        c.rollback();raise
    finally:c.close()
    return None


@operations_bp.after_app_request
def finalize_public_catalog_tracking(response):
    if request.path != '/request-quote' or request.method != 'POST':
        return response
    reservation=getattr(g,'legacy_stock_reservation',None)
    meta=getattr(g,'legacy_order_meta',None) or session.get('_legacy_order_source') or {}
    location=response.headers.get('Location','')
    success=response.status_code in (301,302,303,307,308) and '/request/' in location and '/request-quote' not in location
    if success:
        token=location.split('/request/',1)[1].split('?',1)[0].split('#',1)[0]
        c=db()
        try:
            with c.cursor() as cur:
                cur.execute('''UPDATE customer_requests SET source=%s,utm_source=%s,utm_medium=%s,utm_campaign=%s,
                               reserved_stock_qty=%s WHERE public_token=%s RETURNING id''',
                            (meta.get('source') or 'catalog',meta.get('utm_source') or None,meta.get('utm_medium') or None,
                             meta.get('utm_campaign') or None,(reservation or {}).get('qty',0),token))
                row=cur.fetchone()
                if row:
                    details=f"Origem: {meta.get('source') or 'catalog'}"
                    if reservation:
                        details+=f"; estoque pronto reservado: {reservation['qty']} de {reservation['requested_qty']}"
                    cur.execute("INSERT INTO order_events(request_id,event_type,details) VALUES(%s,'request_received',%s)",(row['id'],details))
            c.commit()
        except Exception:
            c.rollback();raise
        finally:c.close()
    elif reservation and reservation.get('qty'):
        c=db()
        try:
            with c.cursor() as cur:
                cur.execute('UPDATE products SET reserved_stock_qty=GREATEST(0,reserved_stock_qty-%s) WHERE id=%s',(reservation['qty'],reservation['product_id']))
            c.commit()
        finally:c.close()
    return response


@operations_bp.get('/orders')
@login_required
def orders():
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute('''
                SELECT r.id, r.request_number, r.created_at, r.status, r.name AS request_name,
                       r.quantity, r.total_amount, r.currency, r.source, r.product_id, r.quote_id,
                       p.name AS product_name, p.sku,
                       q.quote_number, q.status AS quote_status, q.total AS quote_total,
                       COALESCE(cu.name,r.name) AS customer_name
                FROM customer_requests r
                LEFT JOIN products p ON p.id=r.product_id
                LEFT JOIN quotes q ON q.id=r.quote_id
                LEFT JOIN customers cu ON cu.id=r.customer_id
                ORDER BY r.created_at DESC
            ''')
            items = cur.fetchall()
    finally:
        c.close()
    return render_template('orders.html', items=items)


@operations_bp.get('/orders/<int:request_id>')
@login_required
def order_detail(request_id):
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute('''
                SELECT r.*, p.name AS product_name, p.sku, p.fulfillment_mode, p.stock_qty,p.reserved_stock_qty AS product_reserved_stock_qty,
                       q.quote_number, q.status AS quote_status, q.total AS quote_total,
                       q.filament_id, q.estimated_grams, q.actual_grams,
                       cu.id AS linked_customer_id, cu.name AS linked_customer_name
                FROM customer_requests r
                LEFT JOIN products p ON p.id=r.product_id
                LEFT JOIN quotes q ON q.id=r.quote_id
                LEFT JOIN customers cu ON cu.id=r.customer_id
                WHERE r.id=%s
            ''', (request_id,))
            item = cur.fetchone()
            if not item:
                return 'Pedido não encontrado.', 404
            cur.execute('SELECT id,file_name,file_size FROM customer_request_files WHERE request_id=%s ORDER BY created_at', (request_id,))
            files = cur.fetchall()
            cur.execute('''SELECT event_type,details,created_at FROM order_events
                           WHERE request_id=%s OR quote_id=%s ORDER BY created_at DESC''', (request_id, item['quote_id']))
            events = cur.fetchall()
            batches=[]
            if item['quote_id']:
                cur.execute('''SELECT b.*, p.name AS batch_product_name, f.material, f.color
                               FROM production_batches b JOIN products p ON p.id=b.product_id
                               LEFT JOIN filaments f ON f.id=b.filament_id
                               WHERE b.quote_id=%s ORDER BY b.created_at DESC''', (item['quote_id'],))
                batches=cur.fetchall()
    finally:
        c.close()
    return render_template('order_detail.html', item=item, files=files, events=events, batches=batches)


@operations_bp.get('/reports/sources')
@login_required
def source_report():
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('''SELECT COALESCE(NULLIF(r.source,''),'unknown') AS source,
                                  COALESCE(q.currency,r.currency,'N/A') AS currency,
                                  COUNT(*) AS requests,
                                  COUNT(r.quote_id) AS converted,
                                  COALESCE(SUM(CASE WHEN q.status <> 'canceled' THEN q.total ELSE 0 END),0) AS revenue
                           FROM customer_requests r
                           LEFT JOIN quotes q ON q.id=r.quote_id
                           GROUP BY COALESCE(NULLIF(r.source,''),'unknown'),COALESCE(q.currency,r.currency,'N/A')
                           ORDER BY source,currency''')
            rows=cur.fetchall()
    finally:c.close()
    return render_template('source_report.html',rows=rows)


@operations_bp.get('/audit')
@login_required
def audit_log():
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('''SELECT a.*,u.full_name AS user_name FROM audit_log a
                           LEFT JOIN users u ON u.id=a.user_id ORDER BY a.created_at DESC LIMIT 300''')
            rows=cur.fetchall()
    finally:c.close()
    return render_template('audit_log.html',rows=rows)


@operations_bp.get('/production/stock')
@login_required
def stock_production():
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('''SELECT p.id,p.sku,p.name,p.stock_qty,p.reserved_stock_qty,p.stock_min_qty,p.grams_per_unit,
                                  p.filament_id,p.fulfillment_mode,f.material,f.color
                           FROM products p LEFT JOIN filaments f ON f.id=p.filament_id
                           WHERE p.active=TRUE ORDER BY p.name''')
            products=cur.fetchall()
            cur.execute('''SELECT id,brand,material,color,remaining_g,reserved_g,
                                  (remaining_g-reserved_g) AS available_g FROM filaments ORDER BY material,color''')
            filaments=cur.fetchall()
            cur.execute('''SELECT b.*,p.name AS product_name,p.sku,f.material,f.color,
                                  (f.remaining_g-f.reserved_g) AS filament_available_g
                           FROM production_batches b JOIN products p ON p.id=b.product_id
                           LEFT JOIN filaments f ON f.id=b.filament_id
                           ORDER BY CASE b.status WHEN 'printing' THEN 0 WHEN 'queued' THEN 1 ELSE 2 END,b.created_at DESC''')
            batches=cur.fetchall()
    finally:c.close()
    return render_template('stock_production.html',products=products,filaments=filaments,batches=batches)


@operations_bp.post('/production/stock/create')
@login_required
def create_stock_batch():
    product_id=request.form.get('product_id')
    quantity=max(int(request.form.get('quantity') or 1),1)
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT * FROM products WHERE id=%s FOR UPDATE',(product_id,)); product=cur.fetchone()
            if not product:
                flash('Produto não encontrado.','danger'); return redirect(url_for('operations.stock_production'))
            filament_id=request.form.get('filament_id') or product['filament_id']
            grams_per_unit=d(request.form.get('grams_per_unit'),product['grams_per_unit'] or 0)
            reserve=grams_per_unit*quantity
            if not filament_id or reserve <= 0:
                flash('Defina o filamento e o consumo em gramas por unidade.','danger'); return redirect(url_for('operations.stock_production'))
            cur.execute('SELECT * FROM filaments WHERE id=%s FOR UPDATE',(filament_id,)); filament=cur.fetchone()
            available=d(filament['remaining_g'])-d(filament['reserved_g']) if filament else Decimal('0')
            if not filament or available < reserve:
                flash(f'Filamento disponível insuficiente. Necessário: {reserve} g; disponível: {available} g.','danger'); return redirect(url_for('operations.stock_production'))
            cur.execute('UPDATE filaments SET reserved_g=reserved_g+%s WHERE id=%s',(reserve,filament_id))
            cur.execute('''INSERT INTO production_batches(product_id,filament_id,mode,quantity,grams_per_unit,reserved_g,status,notes)
                           VALUES(%s,%s,'stock',%s,%s,%s,'queued',%s)''',(product_id,filament_id,quantity,grams_per_unit,reserve,request.form.get('notes')))
            cur.execute('''INSERT INTO inventory_movements(filament_id,product_id,grams,movement_type,reference_type,notes,filament_g)
                           VALUES(%s,%s,0,'filament_reserved','production_batch',%s,%s)''',(filament_id,product_id,f'Reservados {reserve} g para produção de estoque',reserve))
        c.commit()
    except Exception:
        c.rollback(); raise
    finally:c.close()
    flash('Lote criado e filamento reservado.','success')
    return redirect(url_for('operations.stock_production'))


@operations_bp.post('/production/stock/<int:batch_id>/start')
@login_required
def start_stock_batch(batch_id):
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute("UPDATE production_batches SET status='printing',started_at=NOW() WHERE id=%s AND status='queued'",(batch_id,))
        c.commit()
    finally:c.close()
    flash('Produção do lote iniciada.','success')
    return redirect(url_for('operations.stock_production'))


@operations_bp.post('/production/stock/<int:batch_id>/complete')
@login_required
def complete_stock_batch(batch_id):
    actual=d(request.form.get('actual_grams'))
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT * FROM production_batches WHERE id=%s FOR UPDATE',(batch_id,)); batch=cur.fetchone()
            if not batch or batch['status'] not in ('queued','printing'):
                flash('Lote não encontrado ou já encerrado.','danger'); return redirect(url_for('operations.stock_production'))
            reserved=d(batch['reserved_g']); actual=actual if actual>0 else reserved
            cur.execute('SELECT * FROM filaments WHERE id=%s FOR UPDATE',(batch['filament_id'],)); filament=cur.fetchone()
            extra=max(Decimal('0'),actual-reserved)
            available=d(filament['remaining_g'])-d(filament['reserved_g'])
            if extra>available:
                flash('Estoque físico insuficiente para registrar o consumo real.','danger'); return redirect(url_for('operations.stock_production'))
            cur.execute('UPDATE filaments SET reserved_g=GREATEST(0,reserved_g-%s),remaining_g=remaining_g-%s WHERE id=%s',(reserved,actual,batch['filament_id']))
            cur.execute('UPDATE products SET stock_qty=stock_qty+%s WHERE id=%s',(batch['quantity'],batch['product_id']))
            cur.execute("UPDATE production_batches SET status='completed',consumed_g=%s,completed_at=NOW() WHERE id=%s",(actual,batch_id))
            cur.execute('''INSERT INTO inventory_movements(filament_id,product_id,grams,movement_type,reference_type,reference_id,notes,product_qty,filament_g)
                           VALUES(%s,%s,%s,'stock_production','production_batch',%s,%s,%s,%s)''',(batch['filament_id'],batch['product_id'],-actual,batch_id,'Produção concluída para estoque',batch['quantity'],-actual))
        c.commit()
    except Exception:
        c.rollback(); raise
    finally:c.close()
    flash('Lote concluído: filamento consumido e peças adicionadas ao estoque pronto.','success')
    return redirect(url_for('operations.stock_production'))


@operations_bp.post('/production/stock/<int:batch_id>/cancel')
@login_required
def cancel_stock_batch(batch_id):
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT * FROM production_batches WHERE id=%s FOR UPDATE',(batch_id,)); batch=cur.fetchone()
            if batch and batch['status'] in ('queued','printing'):
                cur.execute('UPDATE filaments SET reserved_g=GREATEST(0,reserved_g-%s) WHERE id=%s',(batch['reserved_g'],batch['filament_id']))
                cur.execute("UPDATE production_batches SET status='cancelled' WHERE id=%s",(batch_id,))
        c.commit()
    finally:c.close()
    flash('Lote cancelado e reserva de filamento liberada.','success')
    return redirect(url_for('operations.stock_production'))
