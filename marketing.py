import os
from functools import wraps

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, render_template, session, redirect, url_for

marketing_bp = Blueprint('marketing', __name__)
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


@marketing_bp.get('/marketing')
@login_required
def marketing_home():
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute("SELECT id,sku,name,description,price,currency,stock_qty FROM products WHERE active=TRUE ORDER BY created_at DESC")
            products = cur.fetchall()
    finally:
        c.close()
    return render_template('marketing.html', products=products)
