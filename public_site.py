import os

import psycopg2
from flask import Blueprint, render_template, session, redirect, request
from psycopg2.extras import RealDictCursor

public_site_bp = Blueprint('public_site', __name__)
DATABASE_URL = os.getenv('DATABASE_URL')


def _products():
    if not DATABASE_URL:
        return []
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute('''
                SELECT p.id, p.name, p.description, p.price, p.currency,
                       EXISTS(SELECT 1 FROM product_images pi WHERE pi.product_id=p.id) AS has_image
                FROM products p
                WHERE p.active=TRUE
                ORDER BY p.created_at DESC
                LIMIT 8
            ''')
            return cur.fetchall()
    except Exception:
        return []
    finally:
        conn.close()


@public_site_bp.before_app_request
def public_main_domain():
    # Visitors to the main domain see the company website, never the admin login.
    # An authenticated owner keeps the existing dashboard workflow at '/'.
    if request.path == '/' and not session.get('user_id'):
        return redirect('/home')


@public_site_bp.get('/home')
def public_home():
    return render_template('public_home.html', products=_products())


@public_site_bp.get('/admin')
def admin_entry():
    # Private entry point for the Legacy management system.
    if session.get('user_id'):
        return redirect('/')
    return redirect('/login')
