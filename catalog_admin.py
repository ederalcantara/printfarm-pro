import os
import re
import unicodedata
from functools import wraps
from io import BytesIO

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, flash, redirect, render_template, request, send_file, session, url_for

catalog_admin_bp = Blueprint('catalog_admin', __name__)
DATABASE_URL = os.getenv('DATABASE_URL')
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_BATCH_IMAGES = 30
ALLOWED_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/webp'}


def db():return psycopg2.connect(DATABASE_URL,cursor_factory=RealDictCursor)
def ensure_catalog_schema():return

def login_required(view):
    @wraps(view)
    def wrapped(*args,**kwargs):
        if not session.get('user_id'):return redirect(url_for('login'))
        return view(*args,**kwargs)
    return wrapped

@catalog_admin_bp.before_app_request
def products_admin_entry():
    if request.path=='/' and request.args.get('tab')=='catalog' and session.get('user_id'):
        return redirect(url_for('catalog_admin.manage_catalog'))

@catalog_admin_bp.after_app_request
def products_admin_label(response):
    if request.path=='/' and response.mimetype=='text/html':
        html=response.get_data(as_text=True).replace('>Catálogo</a>','>Produtos</a>',1);response.set_data(html);response.headers['Content-Length']=len(response.get_data())
    return response

def read_image(uploaded):
    if not uploaded or not uploaded.filename:return None
    if uploaded.mimetype not in ALLOWED_IMAGE_TYPES:raise ValueError('Use uma foto JPG, PNG ou WEBP.')
    data=uploaded.read(MAX_IMAGE_BYTES+1)
    if len(data)>MAX_IMAGE_BYTES:raise ValueError('A foto deve ter no máximo 8 MB.')
    return data,uploaded.mimetype,uploaded.filename

def name_from_filename(filename):
    base=os.path.splitext(os.path.basename(filename))[0]
    return base.replace('_',' ').replace('-',' ').strip() or 'Nova peça'

def slugify(value):
    value=unicodedata.normalize('NFKD',value).encode('ascii','ignore').decode('ascii').lower()
    return re.sub(r'(^-|-$)','',re.sub(r'[^a-z0-9]+','-',value)) or 'produto'

def form_collection():
    value=request.form.get('collection','catalog');return value if value in ('exclusive','catalog') else 'catalog'
def form_fulfillment():
    value=request.form.get('fulfillment_mode','made_to_order');return value if value in ('ready_stock','made_to_order','both') else 'made_to_order'
def audit(cur,product_id,action,details=''):
    cur.execute("INSERT INTO audit_log(entity_type,entity_id,action,details,user_id) VALUES('product',%s,%s,%s,%s)",(product_id,action,details,session.get('user_id')))

@catalog_admin_bp.get('/catalog/manage')
@login_required
def manage_catalog():
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('''SELECT p.id,p.slug,p.sku,p.name,p.description,p.stock_qty,p.reserved_stock_qty,p.stock_min_qty,p.price,p.cost_estimate,
                                  p.currency,p.active,p.collection,p.display_order,p.fulfillment_mode,p.lead_time_days,p.filament_id,p.grams_per_unit,
                                  p.image_data IS NOT NULL AS has_image,f.material AS filament_material,f.color AS filament_color,
                                  (SELECT COUNT(*) FROM customer_requests r WHERE r.product_id=p.id) AS order_count
                           FROM products p LEFT JOIN filaments f ON f.id=p.filament_id
                           ORDER BY CASE WHEN p.collection='exclusive' THEN 0 ELSE 1 END,p.display_order,p.created_at DESC''');products=cur.fetchall()
            cur.execute('SELECT id,brand,material,color,remaining_g,reserved_g FROM filaments ORDER BY material,color');filaments=cur.fetchall()
    finally:c.close()
    return render_template('catalog_manage.html',products=products,filaments=filaments)

@catalog_admin_bp.post('/catalog/manage/publish-all')
@login_required
def publish_all_catalog_products():
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('UPDATE products SET active=TRUE WHERE active=FALSE AND image_data IS NOT NULL RETURNING id');ids=[r['id'] for r in cur.fetchall()]
            for pid in ids:audit(cur,pid,'published','Publicação em lote')
        c.commit()
    finally:c.close()
    flash(f'{len(ids)} peça(s) publicadas no site.','success');return redirect(url_for('catalog_admin.manage_catalog'))

@catalog_admin_bp.post('/catalog/manage/batch')
@login_required
def batch_catalog_photos():
    uploads=[f for f in request.files.getlist('images') if f and f.filename]
    if not uploads:flash('Selecione pelo menos uma foto.','danger');return redirect(url_for('catalog_admin.manage_catalog'))
    if len(uploads)>MAX_BATCH_IMAGES:flash(f'Envie no máximo {MAX_BATCH_IMAGES} fotos por vez.','danger');return redirect(url_for('catalog_admin.manage_catalog'))
    prepared=[]
    try:
        for uploaded in uploads:prepared.append((name_from_filename(uploaded.filename),read_image(uploaded)))
    except ValueError as exc:flash(f'{uploaded.filename}: {exc}','danger');return redirect(url_for('catalog_admin.manage_catalog'))
    c=db()
    try:
        with c.cursor() as cur:
            for name,image in prepared:
                cur.execute('''INSERT INTO products(sku,name,description,stock_qty,price,currency,active,image_data,image_content_type,image_name,collection,display_order,fulfillment_mode)
                               VALUES(NULL,%s,%s,0,0,'USD',FALSE,%s,%s,%s,'catalog',1000,'made_to_order') RETURNING id''',(name,'Importado em lote — revise os dados antes de publicar.',psycopg2.Binary(image[0]),image[1],image[2]));pid=cur.fetchone()['id']
                cur.execute('UPDATE products SET slug=%s WHERE id=%s',(f'{slugify(name)}-{pid}',pid));audit(cur,pid,'created','Importação em lote')
        c.commit()
    finally:c.close()
    flash(f'{len(prepared)} foto(s) importada(s).','success');return redirect(url_for('catalog_admin.manage_catalog'))

@catalog_admin_bp.post('/catalog/manage/add')
@login_required
def add_catalog_product():
    name=request.form.get('name','').strip()
    if not name:flash('Informe o nome da peça.','danger');return redirect(url_for('catalog_admin.manage_catalog'))
    try:image=read_image(request.files.get('image'))
    except ValueError as exc:flash(str(exc),'danger');return redirect(url_for('catalog_admin.manage_catalog'))
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('''INSERT INTO products(sku,name,description,stock_qty,stock_min_qty,price,cost_estimate,currency,active,image_data,image_content_type,image_name,collection,display_order,fulfillment_mode,lead_time_days,filament_id,grams_per_unit)
                           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',(request.form.get('sku') or None,name,request.form.get('description'),int(request.form.get('stock_qty') or 0),int(request.form.get('stock_min_qty') or 0),request.form.get('price') or 0,request.form.get('cost_estimate') or 0,request.form.get('currency','USD'),request.form.get('active')=='1',psycopg2.Binary(image[0]) if image else None,image[1] if image else None,image[2] if image else None,form_collection(),int(request.form.get('display_order') or 1000),form_fulfillment(),int(request.form.get('lead_time_days') or 0) or None,request.form.get('filament_id') or None,request.form.get('grams_per_unit') or 0));pid=cur.fetchone()['id']
            cur.execute('UPDATE products SET slug=%s WHERE id=%s',(f'{slugify(name)}-{pid}',pid));audit(cur,pid,'created','Produto mestre criado')
        c.commit()
    except psycopg2.errors.UniqueViolation:c.rollback();flash('Esse SKU já existe.','danger');return redirect(url_for('catalog_admin.manage_catalog'))
    finally:c.close()
    flash('Produto mestre adicionado.','success');return redirect(url_for('catalog_admin.manage_catalog'))

@catalog_admin_bp.post('/catalog/manage/<int:product_id>/update')
@login_required
def update_catalog_product(product_id):
    name=request.form.get('name','').strip()
    try:image=read_image(request.files.get('image'))
    except ValueError as exc:flash(str(exc),'danger');return redirect(url_for('catalog_admin.manage_catalog'))
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('''UPDATE products SET slug=%s,sku=%s,name=%s,description=%s,stock_qty=%s,stock_min_qty=%s,price=%s,cost_estimate=%s,currency=%s,active=%s,collection=%s,display_order=%s,fulfillment_mode=%s,lead_time_days=%s,filament_id=%s,grams_per_unit=%s WHERE id=%s''',(f'{slugify(name)}-{product_id}',request.form.get('sku') or None,name,request.form.get('description'),int(request.form.get('stock_qty') or 0),int(request.form.get('stock_min_qty') or 0),request.form.get('price') or 0,request.form.get('cost_estimate') or 0,request.form.get('currency','USD'),request.form.get('active')=='1',form_collection(),int(request.form.get('display_order') or 1000),form_fulfillment(),int(request.form.get('lead_time_days') or 0) or None,request.form.get('filament_id') or None,request.form.get('grams_per_unit') or 0,product_id))
            if image:cur.execute('UPDATE products SET image_data=%s,image_content_type=%s,image_name=%s WHERE id=%s',(psycopg2.Binary(image[0]),image[1],image[2],product_id))
            audit(cur,product_id,'updated','Cadastro mestre alterado')
        c.commit()
    except psycopg2.errors.UniqueViolation:c.rollback();flash('Esse SKU já existe.','danger');return redirect(url_for('catalog_admin.manage_catalog'))
    finally:c.close()
    flash('Produto atualizado.','success');return redirect(url_for('catalog_admin.manage_catalog'))

@catalog_admin_bp.post('/catalog/manage/<int:product_id>/remove-photo')
@login_required
def remove_product_photo(product_id):
    c=db()
    try:
        with c.cursor() as cur:cur.execute('UPDATE products SET image_data=NULL,image_content_type=NULL,image_name=NULL WHERE id=%s',(product_id,));audit(cur,product_id,'photo_removed')
        c.commit()
    finally:c.close()
    flash('Foto removida.','success');return redirect(url_for('catalog_admin.manage_catalog'))

@catalog_admin_bp.post('/catalog/manage/<int:product_id>/delete')
@login_required
def delete_catalog_product(product_id):
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT COUNT(*) AS n FROM customer_requests WHERE product_id=%s',(product_id,));used=cur.fetchone()['n']
            if used:
                cur.execute('UPDATE products SET active=FALSE WHERE id=%s',(product_id,));audit(cur,product_id,'archived','Produto com histórico de pedidos');c.commit();flash('Produto possui pedidos e foi arquivado.','warning');return redirect(url_for('catalog_admin.manage_catalog'))
            cur.execute("INSERT INTO audit_log(entity_type,entity_id,action,details,user_id) VALUES('product',%s,'deleted','Produto sem pedidos',%s)",(product_id,session.get('user_id')));cur.execute('DELETE FROM products WHERE id=%s',(product_id,))
        c.commit()
    finally:c.close()
    flash('Peça excluída.','success');return redirect(url_for('catalog_admin.manage_catalog'))

@catalog_admin_bp.get('/product-image/<int:product_id>')
def product_image(product_id):
    c=db()
    try:
        with c.cursor() as cur:cur.execute('SELECT image_data,image_content_type,image_name FROM products WHERE id=%s',(product_id,));item=cur.fetchone()
    finally:c.close()
    if not item or not item['image_data']:return '',404
    return send_file(BytesIO(bytes(item['image_data'])),mimetype=item['image_content_type'] or 'image/jpeg',download_name=item['image_name'] or f'produto-{product_id}.jpg',max_age=3600)
