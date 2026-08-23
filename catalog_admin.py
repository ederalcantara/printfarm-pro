import os
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


def db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def ensure_catalog_schema():
    if not DATABASE_URL:
        return
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS image_data BYTEA")
            cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS image_content_type VARCHAR(120)")
            cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS image_name VARCHAR(255)")
            cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS collection VARCHAR(30) NOT NULL DEFAULT 'catalog'")
            cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS display_order INTEGER NOT NULL DEFAULT 1000")
            cur.execute("UPDATE products SET collection='exclusive' WHERE lower(COALESCE(sku,'')) ~ '^legacy[ _-]*0*(1[0-4]|[1-9])$' AND collection='catalog'")
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


def read_image(uploaded):
    if not uploaded or not uploaded.filename:
        return None
    if uploaded.mimetype not in ALLOWED_IMAGE_TYPES:
        raise ValueError('Use uma foto JPG, PNG ou WEBP.')
    data = uploaded.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError('A foto deve ter no máximo 8 MB.')
    return data, uploaded.mimetype, uploaded.filename


def name_from_filename(filename):
    base = os.path.splitext(os.path.basename(filename))[0]
    return base.replace('_', ' ').replace('-', ' ').strip() or 'Nova peça'


def form_collection():
    value = request.form.get('collection', 'catalog')
    return value if value in ('exclusive', 'catalog') else 'catalog'


@catalog_admin_bp.get('/catalog/manage')
@login_required
def manage_catalog():
    ensure_catalog_schema()
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute('''SELECT id,sku,name,description,stock_qty,price,currency,active,collection,display_order,
                                  image_data IS NOT NULL AS has_image
                           FROM products
                           ORDER BY CASE WHEN collection='exclusive' THEN 0 ELSE 1 END, display_order, created_at DESC''')
            products = cur.fetchall()
    finally:
        c.close()
    return render_template('catalog_manage.html', products=products)


@catalog_admin_bp.post('/catalog/manage/publish-all')
@login_required
def publish_all_catalog_products():
    ensure_catalog_schema()
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute('UPDATE products SET active=TRUE WHERE active=FALSE AND image_data IS NOT NULL')
            updated = cur.rowcount
        c.commit()
    finally:
        c.close()
    flash(f'{updated} peça(s) publicadas no site.', 'success')
    return redirect(url_for('catalog_admin.manage_catalog'))


@catalog_admin_bp.post('/catalog/manage/batch')
@login_required
def batch_catalog_photos():
    ensure_catalog_schema()
    uploads = [f for f in request.files.getlist('images') if f and f.filename]
    if not uploads:
        flash('Selecione pelo menos uma foto.', 'danger')
        return redirect(url_for('catalog_admin.manage_catalog'))
    if len(uploads) > MAX_BATCH_IMAGES:
        flash(f'Envie no máximo {MAX_BATCH_IMAGES} fotos por vez.', 'danger')
        return redirect(url_for('catalog_admin.manage_catalog'))
    prepared=[]
    try:
        for uploaded in uploads:
            prepared.append((name_from_filename(uploaded.filename), read_image(uploaded)))
    except ValueError as exc:
        flash(f'{uploaded.filename}: {exc}', 'danger')
        return redirect(url_for('catalog_admin.manage_catalog'))
    c=db()
    try:
        with c.cursor() as cur:
            for name,image in prepared:
                cur.execute('''INSERT INTO products
                    (sku,name,description,stock_qty,price,currency,active,image_data,image_content_type,image_name,collection,display_order)
                    VALUES (NULL,%s,%s,0,0,'USD',FALSE,%s,%s,%s,'catalog',1000)''',
                    (name,'Importado em lote — revise os dados, escolha a coleção e publique quando estiver pronto.',psycopg2.Binary(image[0]),image[1],image[2]))
        c.commit()
    finally:c.close()
    flash(f'{len(prepared)} foto(s) importada(s). As peças ficaram ocultas para revisão.', 'success')
    return redirect(url_for('catalog_admin.manage_catalog'))


@catalog_admin_bp.post('/catalog/manage/add')
@login_required
def add_catalog_product():
    ensure_catalog_schema()
    name=request.form.get('name','').strip()
    if not name:
        flash('Informe o nome da peça.','danger'); return redirect(url_for('catalog_admin.manage_catalog'))
    try:image=read_image(request.files.get('image'))
    except ValueError as exc:
        flash(str(exc),'danger'); return redirect(url_for('catalog_admin.manage_catalog'))
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('''INSERT INTO products
                (sku,name,description,stock_qty,price,currency,active,image_data,image_content_type,image_name,collection,display_order)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (request.form.get('sku') or None,name,request.form.get('description'),int(request.form.get('stock_qty') or 0),
                 request.form.get('price') or 0,request.form.get('currency','USD'),request.form.get('active')=='1',
                 psycopg2.Binary(image[0]) if image else None,image[1] if image else None,image[2] if image else None,
                 form_collection(),int(request.form.get('display_order') or 1000)))
        c.commit()
    except psycopg2.errors.UniqueViolation:
        c.rollback(); flash('Esse SKU já existe.','danger'); return redirect(url_for('catalog_admin.manage_catalog'))
    finally:c.close()
    flash('Peça adicionada. O site público seguirá as opções definidas aqui.','success')
    return redirect(url_for('catalog_admin.manage_catalog'))


@catalog_admin_bp.post('/catalog/manage/<int:product_id>/update')
@login_required
def update_catalog_product(product_id):
    ensure_catalog_schema()
    try:image=read_image(request.files.get('image'))
    except ValueError as exc:
        flash(str(exc),'danger'); return redirect(url_for('catalog_admin.manage_catalog'))
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('''UPDATE products SET sku=%s,name=%s,description=%s,stock_qty=%s,price=%s,currency=%s,
                           active=%s,collection=%s,display_order=%s WHERE id=%s''',
                (request.form.get('sku') or None,request.form.get('name','').strip(),request.form.get('description'),
                 int(request.form.get('stock_qty') or 0),request.form.get('price') or 0,request.form.get('currency','USD'),
                 request.form.get('active')=='1',form_collection(),int(request.form.get('display_order') or 1000),product_id))
            if image:
                cur.execute('UPDATE products SET image_data=%s,image_content_type=%s,image_name=%s WHERE id=%s',
                            (psycopg2.Binary(image[0]),image[1],image[2],product_id))
        c.commit()
    except psycopg2.errors.UniqueViolation:
        c.rollback(); flash('Esse SKU já existe.','danger'); return redirect(url_for('catalog_admin.manage_catalog'))
    finally:c.close()
    flash('Peça atualizada. A configuração será refletida automaticamente no site público.','success')
    return redirect(url_for('catalog_admin.manage_catalog'))


@catalog_admin_bp.post('/catalog/manage/<int:product_id>/remove-photo')
@login_required
def remove_product_photo(product_id):
    ensure_catalog_schema(); c=db()
    try:
        with c.cursor() as cur: cur.execute('UPDATE products SET image_data=NULL,image_content_type=NULL,image_name=NULL WHERE id=%s',(product_id,))
        c.commit()
    finally:c.close()
    flash('Foto removida.','success'); return redirect(url_for('catalog_admin.manage_catalog'))


@catalog_admin_bp.post('/catalog/manage/<int:product_id>/delete')
@login_required
def delete_catalog_product(product_id):
    ensure_catalog_schema(); c=db()
    try:
        with c.cursor() as cur: cur.execute('DELETE FROM products WHERE id=%s',(product_id,))
        c.commit()
    finally:c.close()
    flash('Peça excluída do catálogo.','success'); return redirect(url_for('catalog_admin.manage_catalog'))


@catalog_admin_bp.get('/product-image/<int:product_id>')
def product_image(product_id):
    ensure_catalog_schema(); c=db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT image_data,image_content_type,image_name FROM products WHERE id=%s',(product_id,)); item=cur.fetchone()
    finally:c.close()
    if not item or not item['image_data']: return '',404
    return send_file(BytesIO(bytes(item['image_data'])),mimetype=item['image_content_type'] or 'image/jpeg',download_name=item['image_name'] or f'produto-{product_id}.jpg',max_age=3600)
