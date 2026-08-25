import os

import psycopg2
from flask import Blueprint, render_template, session, redirect, request, current_app, abort, url_for
from psycopg2.extras import RealDictCursor

public_site_bp = Blueprint('public_site', __name__)
DATABASE_URL = os.getenv('DATABASE_URL')


def _products(search=''):
    result={'exclusive':[],'catalog':[]}
    if not DATABASE_URL:
        current_app.logger.error('Public catalog: DATABASE_URL is not configured'); return result
    conn=None
    try:
        conn=psycopg2.connect(DATABASE_URL,cursor_factory=RealDictCursor)
        with conn.cursor() as cur:
            params=[];where='WHERE active IS TRUE'
            if search:
                where += " AND (name ILIKE %s OR COALESCE(sku,'') ILIKE %s OR COALESCE(description,'') ILIKE %s)"
                term=f'%{search}%';params=[term,term,term]
            cur.execute(f'''SELECT id,slug,sku,name,description,price,currency,collection,display_order,stock_qty,reserved_stock_qty,
                                  GREATEST(stock_qty-reserved_stock_qty,0) AS available_stock_qty,
                                  fulfillment_mode,lead_time_days,image_data IS NOT NULL AS has_image
                           FROM products {where}
                           ORDER BY display_order ASC,created_at DESC,id DESC''',params)
            for p in cur.fetchall():
                result['exclusive' if p.get('collection')=='exclusive' else 'catalog'].append(p)
        return result
    except Exception:
        current_app.logger.exception('Public catalog failed to load products'); return result
    finally:
        if conn is not None:conn.close()


def _whatsapp_url():
    number=''.join(ch for ch in os.getenv('WHATSAPP_NUMBER','17743757803') if ch.isdigit())
    return f'https://wa.me/{number}?text=Olá%20Legacy%203D%20Studio!%20Gostaria%20de%20mais%20informações.'

@public_site_bp.before_app_request
def public_main_domain():
    if request.path=='/' and not session.get('user_id'):return redirect('/home')

@public_site_bp.get('/home')
def public_home():
    search=request.args.get('q','').strip();groups=_products(search)
    return render_template('public_home.html',exclusive_products=groups['exclusive'],catalog_products=groups['catalog'],whatsapp_url=_whatsapp_url(),search=search)


def _product(where,value):
    c=psycopg2.connect(DATABASE_URL,cursor_factory=RealDictCursor)
    try:
        with c.cursor() as cur:
            cur.execute(f'''SELECT id,slug,sku,name,description,price,currency,stock_qty,reserved_stock_qty,
                                   GREATEST(stock_qty-reserved_stock_qty,0) AS available_stock_qty,
                                   fulfillment_mode,lead_time_days,image_data IS NOT NULL AS has_image
                            FROM products WHERE {where}=%s AND active=TRUE''',(value,));return cur.fetchone()
    finally:c.close()

@public_site_bp.get('/produto/<int:product_id>')
def product_detail(product_id):
    product=_product('id',product_id)
    if not product:abort(404)
    if product.get('slug'):return redirect(url_for('public_site.product_detail_slug',slug=product['slug']),code=301)
    return render_template('public_product.html',product=product,whatsapp_url=_whatsapp_url())

@public_site_bp.get('/produto/<slug>')
def product_detail_slug(slug):
    product=_product('slug',slug)
    if not product:abort(404)
    return render_template('public_product.html',product=product,whatsapp_url=_whatsapp_url())

@public_site_bp.get('/admin')
def admin_entry():
    if session.get('user_id'):return redirect('/')
    return redirect('/login')
