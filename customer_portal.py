import os
import secrets
from datetime import datetime
from io import BytesIO

from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for
from psycopg2.extras import RealDictCursor
import psycopg2
from werkzeug.utils import secure_filename

portal_bp = Blueprint('portal', __name__)
DATABASE_URL = os.getenv('DATABASE_URL')
ALLOWED_EXTENSIONS = {'stl','3mf','obj','step','stp','pdf','png','jpg','jpeg','webp'}
MAX_FILE_BYTES = 15 * 1024 * 1024

SCHEMA = '''
CREATE TABLE IF NOT EXISTS customer_requests (
 id SERIAL PRIMARY KEY,
 request_number VARCHAR(40) UNIQUE NOT NULL,
 public_token VARCHAR(80) UNIQUE NOT NULL,
 name VARCHAR(180) NOT NULL,
 email VARCHAR(180), phone VARCHAR(80),
 request_type VARCHAR(30) NOT NULL DEFAULT 'idea',
 title VARCHAR(220) NOT NULL,
 description TEXT NOT NULL,
 intended_use TEXT,
 quantity INTEGER NOT NULL DEFAULT 1,
 preferred_material VARCHAR(100), preferred_color VARCHAR(100),
 deadline VARCHAR(100), status VARCHAR(40) NOT NULL DEFAULT 'received',
 admin_notes TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS customer_request_files (
 id SERIAL PRIMARY KEY,
 request_id INTEGER NOT NULL REFERENCES customer_requests(id) ON DELETE CASCADE,
 file_name VARCHAR(255) NOT NULL,
 content_type VARCHAR(120), file_size INTEGER NOT NULL,
 file_data BYTEA NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
'''

def conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def ensure():
    c=conn()
    try:
        with c.cursor() as cur: cur.execute(SCHEMA)
        c.commit()
    finally: c.close()

def allowed(name):
    return '.' in name and name.rsplit('.',1)[1].lower() in ALLOWED_EXTENSIONS

@portal_bp.route('/request-quote', methods=['GET','POST'])
def request_quote():
    ensure()
    if request.method == 'POST':
        name=request.form.get('name','').strip(); title=request.form.get('title','').strip(); description=request.form.get('description','').strip()
        email=request.form.get('email','').strip(); phone=request.form.get('phone','').strip()
        if not name or not title or not description or (not email and not phone):
            flash('Informe nome, contato, título e descrição do projeto.', 'danger'); return redirect(url_for('portal.request_quote'))
        files=[f for f in request.files.getlist('files') if f and f.filename]
        for f in files:
            if not allowed(f.filename):
                flash('Arquivo não permitido. Use STL, 3MF, OBJ, STEP, PDF ou imagens.', 'danger'); return redirect(url_for('portal.request_quote'))
        number='WEB-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(2).upper()
        token=secrets.token_urlsafe(24)
        c=conn()
        try:
            with c.cursor() as cur:
                cur.execute('''INSERT INTO customer_requests (request_number,public_token,name,email,phone,request_type,title,description,intended_use,quantity,preferred_material,preferred_color,deadline) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',(number,token,name,email,phone,request.form.get('request_type','idea'),title,description,request.form.get('intended_use'),max(int(request.form.get('quantity') or 1),1),request.form.get('preferred_material'),request.form.get('preferred_color'),request.form.get('deadline')))
                rid=cur.fetchone()['id']
                for f in files:
                    data=f.read(MAX_FILE_BYTES+1)
                    if len(data)>MAX_FILE_BYTES: raise ValueError('Arquivo maior que 15 MB')
                    cur.execute('INSERT INTO customer_request_files (request_id,file_name,content_type,file_size,file_data) VALUES (%s,%s,%s,%s,%s)',(rid,secure_filename(f.filename),f.content_type,len(data),psycopg2.Binary(data)))
            c.commit()
        except ValueError as e:
            c.rollback(); flash(str(e),'danger'); return redirect(url_for('portal.request_quote'))
        finally: c.close()
        return redirect(url_for('portal.request_status', token=token))
    return render_template('request_quote.html')

@portal_bp.get('/request/<token>')
def request_status(token):
    ensure(); c=conn()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT * FROM customer_requests WHERE public_token=%s',(token,)); item=cur.fetchone()
            if item:
                cur.execute('SELECT id,file_name,file_size FROM customer_request_files WHERE request_id=%s ORDER BY created_at',(item['id'],)); files=cur.fetchall()
            else: files=[]
    finally: c.close()
    if not item: return 'Solicitação não encontrada.',404
    return render_template('request_status.html', item=item, files=files)
