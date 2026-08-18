import os
import uuid
import hashlib
from decimal import Decimal, InvalidOperation
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import psycopg2
from psycopg2.extras import RealDictCursor

try:
    import boto3
except Exception:
    boto3 = None

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-secret')
DATABASE_URL = os.environ.get('DATABASE_URL')
app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get('LEGACY_MAX_UPLOAD_MB', '100')) * 1024 * 1024
ALLOWED_EXTENSIONS = {'stl','3mf','obj','gcode','png','jpg','jpeg','webp','pdf'}
STATUS_LABELS = {
    'draft':'Rascunho','awaiting_customer_approval':'Aguardando aprovação',
    'approved_for_execution':'Aprovado / Execução','preparing':'Preparação técnica',
    'printing':'Imprimindo','completed':'Concluído','delivered':'Entregue','cancelled':'Cancelado'
}
ALLOWED_TRANSITIONS = {
    'draft': {'awaiting_customer_approval','cancelled'},
    'awaiting_customer_approval': {'approved_for_execution','cancelled'},
    'approved_for_execution': {'preparing','cancelled'},
    'preparing': {'printing','cancelled'},
    'printing': {'completed','cancelled'},
    'completed': {'delivered'}, 'delivered': set(), 'cancelled': set()
}

def D(v, default='0'):
    try:
        return Decimal(str(default if v in (None,'') else v))
    except (InvalidOperation, ValueError):
        return Decimal(default)

def get_conn():
    if not DATABASE_URL:
        raise RuntimeError('DATABASE_URL não configurada.')
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def q1(sql, params=()):
    c=get_conn()
    try:
        with c.cursor() as cur:
            cur.execute(sql,params); return cur.fetchone()
    finally: c.close()

def qall(sql, params=()):
    c=get_conn()
    try:
        with c.cursor() as cur:
            cur.execute(sql,params); return cur.fetchall()
    finally: c.close()

def init_db():
    path=os.path.join(os.path.dirname(__file__),'schema.sql')
    with open(path,'r',encoding='utf-8') as f: schema=f.read()
    c=get_conn()
    try:
        with c.cursor() as cur:
            cur.execute(schema)
            u=os.environ.get('LEGACY_ADMIN_USER','admin')
            p=os.environ.get('LEGACY_ADMIN_PASSWORD','admin123')
            n=os.environ.get('LEGACY_ADMIN_NAME','Legacy Admin')
            cur.execute('SELECT id FROM legacy_users WHERE username=%s',(u,))
            if not cur.fetchone():
                cur.execute("INSERT INTO legacy_users(username,password_hash,full_name,role) VALUES(%s,%s,%s,'admin')",(u,generate_password_hash(p),n))
        c.commit()
    finally: c.close()

_initialized=False
@app.before_request
def ensure_db():
    global _initialized
    if not _initialized:
        init_db(); _initialized=True

def login_required(fn):
    @wraps(fn)
    def w(*a,**kw):
        if not session.get('legacy_user_id'):
            return redirect(url_for('login',next=request.path))
        return fn(*a,**kw)
    return w

@app.template_filter('money')
def money(v,currency='USD'):
    v=D(v); return (f'R$ {v:,.2f}' if currency=='BRL' else f'$ {v:,.2f}')
@app.template_filter('grams')
def grams(v): return f'{D(v):,.0f} g'
@app.context_processor
def ctx(): return {'STATUS_LABELS':STATUS_LABELS}

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        user=q1('SELECT * FROM legacy_users WHERE username=%s AND active=TRUE',(request.form.get('username','').strip(),))
        if user and check_password_hash(user['password_hash'],request.form.get('password','')):
            session['legacy_user_id']=user['id']; session['legacy_user_name']=user['full_name'] or user['username']
            return redirect(request.args.get('next') or url_for('dashboard'))
        flash('Usuário ou senha inválidos.','danger')
    return render_template('login.html')

@app.get('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

@app.get('/health')
def health():
    try: return jsonify({'ok':True,'system':'Sistema Legacy','db':bool(q1('SELECT NOW() now'))})
    except Exception as e: return jsonify({'ok':False,'error':str(e)}),500

@app.get('/')
@login_required
def dashboard():
    stats=q1("""SELECT
      (SELECT COUNT(*) FROM legacy_customers) customers,
      (SELECT COUNT(*) FROM legacy_filaments WHERE active=TRUE) filaments,
      (SELECT COUNT(*) FROM legacy_quotes WHERE status NOT IN ('delivered','cancelled')) open_quotes,
      (SELECT COUNT(*) FROM legacy_quotes WHERE status='printing') printing,
      (SELECT COUNT(*) FROM legacy_projects WHERE project_type='legacy' AND status!='archived') legacy_projects,
      (SELECT COALESCE(SUM(total),0) FROM legacy_quotes WHERE status IN ('completed','delivered') AND currency='USD') revenue_usd""")
    low=qall('SELECT * FROM legacy_filaments WHERE active=TRUE AND weight_remaining_g<=min_stock_g ORDER BY weight_remaining_g LIMIT 8')
    pipe=qall("""SELECT q.*,c.name customer_name,p.name project_name FROM legacy_quotes q
      JOIN legacy_customers c ON c.id=q.customer_id LEFT JOIN legacy_projects p ON p.id=q.project_id
      WHERE q.status NOT IN ('delivered','cancelled') ORDER BY q.updated_at DESC LIMIT 12""")
    return render_template('app.html',page='dashboard',stats=stats,low_stock=low,pipeline=pipe)

@app.get('/customers')
@login_required
def customers():
    rows=qall('SELECT c.*,(SELECT COUNT(*) FROM legacy_quotes q WHERE q.customer_id=c.id) quote_count FROM legacy_customers c ORDER BY c.name')
    return render_template('app.html',page='customers',rows=rows)

@app.route('/customers/new',methods=['GET','POST'])
@login_required
def customer_new():
    if request.method=='POST':
        f=request.form;c=get_conn()
        try:
            with c.cursor() as cur:
                cur.execute("""INSERT INTO legacy_customers(name,email,phone,company,address,city,state,zip_code,instagram,facebook,notes)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (f['name'],f.get('email'),f.get('phone'),f.get('company'),f.get('address'),f.get('city'),f.get('state'),f.get('zip_code'),f.get('instagram'),f.get('facebook'),f.get('notes')))
                cid=cur.fetchone()['id']
            c.commit(); flash('Cliente cadastrado.','success'); return redirect(url_for('customer_detail',customer_id=cid))
        finally:c.close()
    return render_template('app.html',page='customer_form',customer=None)

@app.get('/customers/<int:customer_id>')
@login_required
def customer_detail(customer_id):
    customer=q1('SELECT * FROM legacy_customers WHERE id=%s',(customer_id,))
    if not customer: return redirect(url_for('customers'))
    quotes=qall('SELECT * FROM legacy_quotes WHERE customer_id=%s ORDER BY created_at DESC',(customer_id,))
    projects=qall('SELECT * FROM legacy_projects WHERE customer_id=%s ORDER BY created_at DESC',(customer_id,))
    return render_template('app.html',page='customer_detail',customer=customer,quotes=quotes,projects=projects)

@app.get('/inventory')
@login_required
def inventory():
    rows=qall('SELECT * FROM legacy_filaments WHERE active=TRUE ORDER BY material,color,name')
    mov=qall("""SELECT m.*,f.name filament_name,q.quote_number FROM legacy_inventory_movements m
      JOIN legacy_filaments f ON f.id=m.filament_id LEFT JOIN legacy_quotes q ON q.id=m.quote_id
      ORDER BY m.created_at DESC LIMIT 30""")
    return render_template('app.html',page='inventory',rows=rows,movements=mov)

@app.route('/inventory/new',methods=['GET','POST'])
@login_required
def inventory_new():
    if request.method=='POST':
        f=request.form;total=D(f.get('weight_total_g'));c=get_conn()
        try:
            with c.cursor() as cur:
                cur.execute("""INSERT INTO legacy_filaments(name,brand,material,color,color_hex,sku,supplier,location,weight_total_g,weight_remaining_g,cost_per_kg,currency,min_stock_g)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (f['name'],f.get('brand'),f['material'],f.get('color'),f.get('color_hex'),f.get('sku'),f.get('supplier'),f.get('location'),total,total,D(f.get('cost_per_kg')),f.get('currency','USD'),D(f.get('min_stock_g'),'100')))
                fid=cur.fetchone()['id']
                cur.execute("INSERT INTO legacy_inventory_movements(filament_id,movement_type,quantity_g,signed_quantity_g,reason,note) VALUES(%s,'in',%s,%s,'initial_stock','Cadastro inicial')",(fid,total,total))
            c.commit(); flash('Filamento cadastrado.','success'); return redirect(url_for('inventory'))
        finally:c.close()
    return render_template('app.html',page='inventory_form')

@app.post('/inventory/<int:filament_id>/adjust')
@login_required
def inventory_adjust(filament_id):
    qty=D(request.form.get('quantity_g')); signed=qty if request.form.get('direction','in')=='in' else -qty;c=get_conn()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT weight_remaining_g FROM legacy_filaments WHERE id=%s FOR UPDATE',(filament_id,));r=cur.fetchone()
            if not r or D(r['weight_remaining_g'])+signed<0:
                c.rollback();flash('Ajuste inválido.','danger');return redirect(url_for('inventory'))
            cur.execute('UPDATE legacy_filaments SET weight_remaining_g=weight_remaining_g+%s,updated_at=NOW() WHERE id=%s',(signed,filament_id))
            cur.execute("INSERT INTO legacy_inventory_movements(filament_id,movement_type,quantity_g,signed_quantity_g,reason,note) VALUES(%s,'adjustment',%s,%s,%s,%s)",(filament_id,abs(qty),signed,request.form.get('reason','manual_adjustment'),request.form.get('note')))
        c.commit();flash('Estoque ajustado.','success')
    finally:c.close()
    return redirect(url_for('inventory'))

def next_number(prefix,table,col):
    base=f"{prefix}-{datetime.now().strftime('%Y%m%d')}-";r=q1(f'SELECT {col} num FROM {table} WHERE {col} LIKE %s ORDER BY id DESC LIMIT 1',(base+'%',));n=1
    if r:
        try:n=int(r['num'].split('-')[-1])+1
        except:n=1
    return f'{base}{n:03d}'

@app.get('/projects')
@login_required
def projects():
    t=request.args.get('type','all');where='';params=()
    if t in ('customer','legacy'):where='WHERE p.project_type=%s';params=(t,)
    rows=qall(f"SELECT p.*,c.name customer_name,(SELECT COUNT(*) FROM legacy_project_files f WHERE f.project_id=p.id) file_count FROM legacy_projects p LEFT JOIN legacy_customers c ON c.id=p.customer_id {where} ORDER BY p.updated_at DESC",params)
    return render_template('app.html',page='projects',rows=rows,ptype=t)

@app.route('/projects/new',methods=['GET','POST'])
@login_required
def project_new():
    customers=qall('SELECT id,name FROM legacy_customers ORDER BY name')
    if request.method=='POST':
        f=request.form;t=f.get('project_type','legacy');cid=f.get('customer_id') or None
        if t=='customer' and not cid:flash('Projeto de cliente precisa de cliente.','danger');return render_template('app.html',page='project_form',customers=customers)
        num=next_number('LP' if t=='legacy' else 'CP','legacy_projects','project_number');c=get_conn()
        try:
            with c.cursor() as cur:
                cur.execute("INSERT INTO legacy_projects(project_number,project_type,customer_id,name,description,status,currency,target_price,notes) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",(num,t,cid,f['name'],f.get('description'),f.get('status','idea'),f.get('currency','USD'),D(f.get('target_price')),f.get('notes')));pid=cur.fetchone()['id']
            c.commit();flash('Projeto criado.','success');return redirect(url_for('project_detail',project_id=pid))
        finally:c.close()
    return render_template('app.html',page='project_form',customers=customers)

@app.get('/projects/<int:project_id>')
@login_required
def project_detail(project_id):
    project=q1('SELECT p.*,c.name customer_name FROM legacy_projects p LEFT JOIN legacy_customers c ON c.id=p.customer_id WHERE p.id=%s',(project_id,))
    if not project:return redirect(url_for('projects'))
    files=qall('SELECT * FROM legacy_project_files WHERE project_id=%s ORDER BY created_at DESC',(project_id,));products=qall('SELECT * FROM legacy_catalog_products WHERE project_id=%s ORDER BY created_at DESC',(project_id,))
    return render_template('app.html',page='project_detail',project=project,files=files,products=products)

def upload_to_storage(fileobj,project_id,filename):
    raw=fileobj.read();checksum=hashlib.sha256(raw).hexdigest();ext=filename.rsplit('.',1)[-1].lower() if '.' in filename else '';key=f'projects/{project_id}/{uuid.uuid4().hex}.{ext}';bucket=os.environ.get('S3_BUCKET')
    if boto3 and bucket and os.environ.get('S3_ENDPOINT_URL'):
        cli=boto3.client('s3',endpoint_url=os.environ.get('S3_ENDPOINT_URL'),aws_access_key_id=os.environ.get('S3_ACCESS_KEY_ID'),aws_secret_access_key=os.environ.get('S3_SECRET_ACCESS_KEY'),region_name=os.environ.get('S3_REGION') or 'auto')
        cli.put_object(Bucket=bucket,Key=key,Body=raw,ContentType=fileobj.mimetype or 'application/octet-stream');base=os.environ.get('S3_PUBLIC_BASE_URL','').rstrip('/');return key,(f'{base}/{key}' if base else None),checksum,len(raw),None
    return None,None,checksum,len(raw),'Armazenamento externo ainda não configurado; metadados registrados.'

@app.post('/projects/<int:project_id>/files')
@login_required
def project_file_upload(project_id):
    file=request.files.get('file')
    if not file or not file.filename:flash('Selecione um arquivo.','danger');return redirect(url_for('project_detail',project_id=project_id))
    name=secure_filename(file.filename);ext=name.rsplit('.',1)[-1].lower() if '.' in name else ''
    if ext not in ALLOWED_EXTENSIONS:flash('Tipo de arquivo não permitido.','danger');return redirect(url_for('project_detail',project_id=project_id))
    key,url,checksum,size,warn=upload_to_storage(file,project_id,name);ft='stl' if ext in {'stl','3mf','obj'} else ('gcode' if ext=='gcode' else ('image' if ext in {'png','jpg','jpeg','webp'} else 'other'));c=get_conn()
    try:
        with c.cursor() as cur:cur.execute("INSERT INTO legacy_project_files(project_id,file_type,original_name,storage_key,storage_url,checksum_sha256,version_label,size_bytes,status,notes) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s)",(project_id,ft,name,key,url,checksum,request.form.get('version_label','v1'),size,request.form.get('notes')))
        c.commit()
    finally:c.close()
    flash(warn or 'Arquivo enviado.','warning' if warn else 'success');return redirect(url_for('project_detail',project_id=project_id))

@app.get('/quotes')
@login_required
def quotes():
    rows=qall('SELECT q.*,c.name customer_name,p.name project_name FROM legacy_quotes q JOIN legacy_customers c ON c.id=q.customer_id LEFT JOIN legacy_projects p ON p.id=q.project_id ORDER BY q.created_at DESC')
    return render_template('app.html',page='quotes',rows=rows)

@app.route('/quotes/new',methods=['GET','POST'])
@login_required
def quote_new():
    customers=qall('SELECT id,name FROM legacy_customers ORDER BY name');projects=qall("SELECT id,name,customer_id FROM legacy_projects WHERE project_type='customer' ORDER BY name")
    if request.method=='POST':
        f=request.form;num=next_number('Q','legacy_quotes','quote_number');c=get_conn()
        try:
            with c.cursor() as cur:
                cur.execute("INSERT INTO legacy_quotes(quote_number,customer_id,project_id,status,currency,exchange_rate_to_brl,valid_until,customer_notes,internal_notes) VALUES(%s,%s,%s,'draft',%s,%s,%s,%s,%s) RETURNING id",(num,f['customer_id'],f.get('project_id') or None,f.get('currency','USD'),D(f.get('exchange_rate_to_brl')) if f.get('exchange_rate_to_brl') else None,f.get('valid_until') or None,f.get('customer_notes'),f.get('internal_notes')));qid=cur.fetchone()['id']
            c.commit();flash('Orçamento criado.','success');return redirect(url_for('quote_detail',quote_id=qid))
        finally:c.close()
    return render_template('app.html',page='quote_form',customers=customers,projects=projects)

@app.get('/quotes/<int:quote_id>')
@login_required
def quote_detail(quote_id):
    quote=q1('SELECT q.*,c.name customer_name,c.email customer_email,c.phone customer_phone,p.name project_name FROM legacy_quotes q JOIN legacy_customers c ON c.id=q.customer_id LEFT JOIN legacy_projects p ON p.id=q.project_id WHERE q.id=%s',(quote_id,))
    if not quote:return redirect(url_for('quotes'))
    items=qall('SELECT qi.*,f.name filament_name,m.name machine_name,pf.original_name file_name FROM legacy_quote_items qi LEFT JOIN legacy_filaments f ON f.id=qi.filament_id LEFT JOIN legacy_machines m ON m.id=qi.machine_id LEFT JOIN legacy_project_files pf ON pf.id=qi.project_file_id WHERE qi.quote_id=%s ORDER BY qi.id',(quote_id,));fil=qall('SELECT id,name,material,color,weight_remaining_g FROM legacy_filaments WHERE active=TRUE ORDER BY name');machines=qall('SELECT id,name,status FROM legacy_machines ORDER BY name');files=qall('SELECT id,original_name,version_label FROM legacy_project_files WHERE project_id=%s ORDER BY created_at DESC',(quote['project_id'],)) if quote['project_id'] else [];mov=qall('SELECT im.*,f.name filament_name FROM legacy_inventory_movements im JOIN legacy_filaments f ON f.id=im.filament_id WHERE im.quote_id=%s ORDER BY im.created_at',(quote_id,))
    return render_template('app.html',page='quote_detail',quote=quote,items=items,filaments=fil,machines=machines,files=files,movements=mov)

def recalc_quote(c,qid):
    with c.cursor() as cur:
        cur.execute('SELECT COALESCE(SUM(line_total),0) subtotal FROM legacy_quote_items WHERE quote_id=%s',(qid,));sub=D(cur.fetchone()['subtotal']);cur.execute('SELECT tax,shipping FROM legacy_quotes WHERE id=%s',(qid,));q=cur.fetchone();cur.execute('UPDATE legacy_quotes SET subtotal=%s,total=%s,updated_at=NOW() WHERE id=%s',(sub,sub+D(q['tax'])+D(q['shipping']),qid))

@app.post('/quotes/<int:quote_id>/items')
@login_required
def quote_item_add(quote_id):
    f=request.form;qty=int(f.get('quantity') or 1);price=D(f.get('unit_price'));c=get_conn()
    try:
        with c.cursor() as cur:cur.execute("""INSERT INTO legacy_quote_items(quote_id,description,quantity,filament_id,machine_id,project_file_id,estimated_filament_g,print_time_hours,labor_hours,layer_height_mm,infill_percent,size_x_mm,size_y_mm,size_z_mm,unit_cost,unit_price,line_total)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",(quote_id,f['description'],qty,f.get('filament_id') or None,f.get('machine_id') or None,f.get('project_file_id') or None,D(f.get('estimated_filament_g')),D(f.get('print_time_hours')),D(f.get('labor_hours')),D(f.get('layer_height_mm')) if f.get('layer_height_mm') else None,D(f.get('infill_percent')) if f.get('infill_percent') else None,D(f.get('size_x_mm')) if f.get('size_x_mm') else None,D(f.get('size_y_mm')) if f.get('size_y_mm') else None,D(f.get('size_z_mm')) if f.get('size_z_mm') else None,D(f.get('unit_cost')),price,price*qty))
        recalc_quote(c,quote_id);c.commit();flash('Item adicionado.','success')
    finally:c.close()
    return redirect(url_for('quote_detail',quote_id=quote_id))

def deduct_inventory(c,qid):
    with c.cursor() as cur:
        cur.execute('SELECT qi.id,qi.filament_id,(qi.estimated_filament_g*qi.quantity) total_g,f.weight_remaining_g FROM legacy_quote_items qi JOIN legacy_filaments f ON f.id=qi.filament_id WHERE qi.quote_id=%s AND qi.filament_id IS NOT NULL AND qi.estimated_filament_g>0 FOR UPDATE OF f',(qid,));rows=cur.fetchall()
        if any(D(r['weight_remaining_g'])<D(r['total_g']) for r in rows):return False
        for r in rows:
            need=D(r['total_g']);cur.execute("INSERT INTO legacy_inventory_movements(filament_id,quote_id,quote_item_id,movement_type,quantity_g,signed_quantity_g,reason,note) VALUES(%s,%s,%s,'out',%s,%s,'printing_start','Baixa automática ao iniciar impressão') ON CONFLICT(quote_item_id,reason) DO NOTHING RETURNING id",(r['filament_id'],qid,r['id'],need,-need))
            if cur.fetchone():cur.execute('UPDATE legacy_filaments SET weight_remaining_g=weight_remaining_g-%s,updated_at=NOW() WHERE id=%s',(need,r['filament_id']))
        return True

def adjust_actual(c,qid):
    with c.cursor() as cur:
        cur.execute('SELECT id,filament_id,quantity,estimated_filament_g,actual_filament_g FROM legacy_quote_items WHERE quote_id=%s AND filament_id IS NOT NULL AND actual_filament_g IS NOT NULL',(qid,))
        for r in cur.fetchall():
            diff=D(r['actual_filament_g'])*int(r['quantity'])-D(r['estimated_filament_g'])*int(r['quantity'])
            if diff==0:continue
            cur.execute("INSERT INTO legacy_inventory_movements(filament_id,quote_id,quote_item_id,movement_type,quantity_g,signed_quantity_g,reason,note) VALUES(%s,%s,%s,'adjustment',%s,%s,'actual_usage_adjustment','Ajuste pelo consumo real') ON CONFLICT(quote_item_id,reason) DO NOTHING RETURNING id",(r['filament_id'],qid,r['id'],abs(diff),-diff))
            if cur.fetchone():cur.execute('UPDATE legacy_filaments SET weight_remaining_g=weight_remaining_g-%s,updated_at=NOW() WHERE id=%s AND weight_remaining_g-%s>=0',(diff,r['filament_id'],diff))

@app.post('/quotes/<int:quote_id>/status')
@login_required
def quote_status(quote_id):
    new=request.form.get('status');c=get_conn()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT * FROM legacy_quotes WHERE id=%s FOR UPDATE',(quote_id,));q=cur.fetchone()
            if not q:return redirect(url_for('quotes'))
            if new==q['status']:return redirect(url_for('quote_detail',quote_id=quote_id))
            if new not in ALLOWED_TRANSITIONS.get(q['status'],set()):c.rollback();flash('Transição de status inválida.','danger');return redirect(url_for('quote_detail',quote_id=quote_id))
            if new=='printing' and not deduct_inventory(c,quote_id):c.rollback();flash('Estoque insuficiente para iniciar a impressão.','danger');return redirect(url_for('quote_detail',quote_id=quote_id))
            if new=='completed':adjust_actual(c,quote_id)
            extra=''
            if new=='approved_for_execution':extra=',customer_approved_at=COALESCE(customer_approved_at,NOW())'
            elif new=='printing':extra=',printing_started_at=COALESCE(printing_started_at,NOW())'
            elif new=='completed':extra=',completed_at=COALESCE(completed_at,NOW())'
            elif new=='delivered':extra=',delivered_at=COALESCE(delivered_at,NOW())'
            cur.execute(f'UPDATE legacy_quotes SET status=%s,updated_at=NOW(){extra} WHERE id=%s',(new,quote_id))
        c.commit();flash('Status atualizado.','success')
    finally:c.close()
    return redirect(url_for('quote_detail',quote_id=quote_id))

@app.post('/quote-items/<int:item_id>/actual')
@login_required
def quote_item_actual(item_id):
    r=q1('SELECT quote_id FROM legacy_quote_items WHERE id=%s',(item_id,));c=get_conn()
    try:
        with c.cursor() as cur:cur.execute('UPDATE legacy_quote_items SET actual_filament_g=%s,updated_at=NOW() WHERE id=%s',(D(request.form.get('actual_filament_g')),item_id))
        c.commit()
    finally:c.close()
    return redirect(url_for('quote_detail',quote_id=r['quote_id']))

@app.route('/machines',methods=['GET','POST'])
@login_required
def machines():
    if request.method=='POST':
        f=request.form;c=get_conn()
        try:
            with c.cursor() as cur:cur.execute('INSERT INTO legacy_machines(name,brand,model,status,notes) VALUES(%s,%s,%s,%s,%s)',(f['name'],f.get('brand'),f.get('model'),f.get('status','idle'),f.get('notes')))
            c.commit();flash('Máquina cadastrada.','success')
        finally:c.close()
        return redirect(url_for('machines'))
    return render_template('app.html',page='machines',rows=qall('SELECT * FROM legacy_machines ORDER BY name'))

@app.get('/catalog')
@login_required
def catalog():return render_template('app.html',page='catalog',rows=qall('SELECT cp.*,p.project_number,p.name project_name FROM legacy_catalog_products cp JOIN legacy_projects p ON p.id=cp.project_id WHERE cp.active=TRUE ORDER BY cp.name'))

@app.post('/projects/<int:project_id>/catalog')
@login_required
def catalog_add(project_id):
    f=request.form;c=get_conn()
    try:
        with c.cursor() as cur:
            cur.execute('INSERT INTO legacy_catalog_products(project_id,sku,name,description,currency,price,cost,ready_stock,instagram_caption,facebook_caption) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(project_id,f.get('sku') or None,f['name'],f.get('description'),f.get('currency','USD'),D(f.get('price')),D(f.get('cost')),int(f.get('ready_stock') or 0),f.get('instagram_caption'),f.get('facebook_caption')));cur.execute("UPDATE legacy_projects SET status='catalog',updated_at=NOW() WHERE id=%s",(project_id,))
        c.commit();flash('Produto adicionado ao catálogo.','success')
    finally:c.close()
    return redirect(url_for('project_detail',project_id=project_id))

@app.post('/catalog/<int:product_id>/stock')
@login_required
def finished_stock(product_id):
    qty=int(request.form.get('quantity') or 0);direction=request.form.get('direction','in');signed=qty if direction=='in' else -qty;c=get_conn()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT ready_stock FROM legacy_catalog_products WHERE id=%s FOR UPDATE',(product_id,));p=cur.fetchone()
            if not p or int(p['ready_stock'])+signed<0:c.rollback();flash('Movimentação inválida.','danger');return redirect(url_for('catalog'))
            cur.execute('UPDATE legacy_catalog_products SET ready_stock=ready_stock+%s,updated_at=NOW() WHERE id=%s',(signed,product_id));cur.execute('INSERT INTO legacy_finished_goods_movements(product_id,movement_type,quantity,signed_quantity,reason) VALUES(%s,%s,%s,%s,%s)',(product_id,direction,qty,signed,request.form.get('reason','manual')))
        c.commit();flash('Estoque de produto atualizado.','success')
    finally:c.close()
    return redirect(url_for('catalog'))

@app.get('/production')
@login_required
def production():
    rows=qall("SELECT q.*,c.name customer_name,p.name project_name FROM legacy_quotes q JOIN legacy_customers c ON c.id=q.customer_id LEFT JOIN legacy_projects p ON p.id=q.project_id WHERE q.status IN ('approved_for_execution','preparing','printing','completed') ORDER BY q.updated_at")
    return render_template('app.html',page='production',rows=rows)

if __name__=='__main__':
    init_db();app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)),debug=os.environ.get('FLASK_DEBUG')=='1')
