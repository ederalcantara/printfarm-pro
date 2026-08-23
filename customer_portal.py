import os
import secrets
from datetime import datetime
from decimal import Decimal
from io import BytesIO

from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for
from psycopg2.extras import RealDictCursor
import psycopg2
from werkzeug.utils import secure_filename
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

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
 product_id INTEGER,
 unit_price NUMERIC(12,2),
 currency VARCHAR(3),
 total_amount NUMERIC(12,2),
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
ALTER TABLE customer_requests ADD COLUMN IF NOT EXISTS product_id INTEGER;
ALTER TABLE customer_requests ADD COLUMN IF NOT EXISTS unit_price NUMERIC(12,2);
ALTER TABLE customer_requests ADD COLUMN IF NOT EXISTS currency VARCHAR(3);
ALTER TABLE customer_requests ADD COLUMN IF NOT EXISTS total_amount NUMERIC(12,2);
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

def active_products():
    c=conn()
    try:
        with c.cursor() as cur:
            cur.execute("SELECT id,sku,name,description,price,currency,stock_qty,(image_data IS NOT NULL) AS has_image FROM products WHERE active=TRUE ORDER BY created_at DESC")
            return cur.fetchall()
    finally:
        c.close()

def money(value, currency='USD'):
    if value is None:
        return 'A definir'
    symbol = 'R$' if currency == 'BRL' else '$'
    return f"{symbol} {Decimal(value):,.2f}"

def request_record(token):
    ensure(); c=conn()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT * FROM customer_requests WHERE public_token=%s',(token,)); item=cur.fetchone()
            if item:
                cur.execute('SELECT id,file_name,file_size FROM customer_request_files WHERE request_id=%s ORDER BY created_at',(item['id'],)); files=cur.fetchall()
            else:
                files=[]
    finally:
        c.close()
    return item, files

@portal_bp.route('/request-quote', methods=['GET','POST'])
def request_quote():
    ensure()
    if request.method == 'POST':
        name=request.form.get('name','').strip()
        email=request.form.get('email','').strip()
        phone=request.form.get('phone','').strip()
        mode=request.form.get('mode','custom')
        quantity=max(int(request.form.get('quantity') or 1),1)

        if not name or (not email and not phone):
            flash('Informe seu nome e pelo menos um contato.', 'danger')
            return redirect(url_for('portal.request_quote'))

        product=None
        unit_price=None
        currency=None
        total_amount=None
        if mode == 'catalog':
            product_id=request.form.get('product_id')
            if not product_id:
                flash('Escolha uma peça do catálogo.', 'danger')
                return redirect(url_for('portal.request_quote') + '#catalogo')
            c=conn()
            try:
                with c.cursor() as cur:
                    cur.execute("SELECT id,sku,name,description,price,currency FROM products WHERE id=%s AND active=TRUE", (product_id,))
                    product=cur.fetchone()
            finally:
                c.close()
            if not product:
                flash('Essa peça não está mais disponível no catálogo.', 'danger')
                return redirect(url_for('portal.request_quote') + '#catalogo')
            title=product['name']
            customer_note=request.form.get('catalog_notes','').strip()
            unit_price=Decimal(product['price'] or 0)
            currency=product['currency'] or 'USD'
            total_amount=unit_price * quantity
            description=(f"Pedido de peça do Catálogo Legacy. SKU: {product['sku'] or '-'}; "
                         f"Preço exibido: {currency} {unit_price}; Quantidade: {quantity}.")
            if customer_note:
                description += "\nObservação do cliente: " + customer_note
            request_type='catalog'
            deadline=request.form.get('catalog_deadline','').strip()
            files=[]
        else:
            title=request.form.get('title','').strip()
            description=request.form.get('description','').strip()
            if not title or not description:
                flash('Informe o título e descreva o que você quer.', 'danger')
                return redirect(url_for('portal.request_quote'))
            request_type=request.form.get('request_type','idea')
            deadline=request.form.get('deadline','').strip()
            files=[f for f in request.files.getlist('files') if f and f.filename]
            for f in files:
                if not allowed(f.filename):
                    flash('Arquivo não permitido. Use STL, 3MF, OBJ, STEP, PDF ou imagens.', 'danger')
                    return redirect(url_for('portal.request_quote'))

        number='WEB-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(2).upper()
        token=secrets.token_urlsafe(24)
        c=conn()
        try:
            with c.cursor() as cur:
                cur.execute('''INSERT INTO customer_requests
                    (request_number,public_token,name,email,phone,request_type,title,description,quantity,deadline,admin_notes,
                     product_id,unit_price,currency,total_amount)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
                    (number,token,name,email,phone,request_type,title,description,quantity,deadline,
                     ('Produto de catálogo ID '+str(product['id'])) if product else None,
                     product['id'] if product else None, unit_price, currency, total_amount))
                rid=cur.fetchone()['id']
                for f in files:
                    data=f.read(MAX_FILE_BYTES+1)
                    if len(data)>MAX_FILE_BYTES: raise ValueError('Arquivo maior que 15 MB')
                    cur.execute('INSERT INTO customer_request_files (request_id,file_name,content_type,file_size,file_data) VALUES (%s,%s,%s,%s,%s)',
                                (rid,secure_filename(f.filename),f.content_type,len(data),psycopg2.Binary(data)))
            c.commit()
        except ValueError as e:
            c.rollback(); flash(str(e),'danger'); return redirect(url_for('portal.request_quote'))
        finally: c.close()
        return redirect(url_for('portal.request_status', token=token))

    return render_template('request_quote.html', products=active_products(), selected_product=request.args.get('product',''))

@portal_bp.get('/request/<token>')
def request_status(token):
    item, files = request_record(token)
    if not item: return 'Solicitação não encontrada.',404
    return render_template('request_status.html', item=item, files=files, money=money)

@portal_bp.get('/request/<token>/confirmation.pdf')
def request_confirmation_pdf(token):
    item, _ = request_record(token)
    if not item:
        return 'Solicitação não encontrada.', 404

    buf=BytesIO()
    doc=SimpleDocTemplate(buf,pagesize=A4,rightMargin=18*mm,leftMargin=18*mm,topMargin=18*mm,bottomMargin=18*mm,
                          title=f"Confirmação {item['request_number']}")
    styles=getSampleStyleSheet()
    title_style=ParagraphStyle('LegacyTitle',parent=styles['Title'],fontName='Helvetica-Bold',fontSize=20,textColor=colors.HexColor('#111827'),spaceAfter=2)
    sub_style=ParagraphStyle('LegacySub',parent=styles['Normal'],fontSize=9,textColor=colors.HexColor('#6B7280'),spaceAfter=12)
    right_style=ParagraphStyle('Right',parent=styles['Normal'],alignment=TA_RIGHT,fontSize=9,textColor=colors.HexColor('#4B5563'))
    small=ParagraphStyle('Small',parent=styles['Normal'],fontSize=9,leading=13,textColor=colors.HexColor('#374151'))
    h=ParagraphStyle('H',parent=styles['Heading2'],fontName='Helvetica-Bold',fontSize=13,textColor=colors.HexColor('#111827'),spaceBefore=10,spaceAfter=6)
    story=[]

    brand=Table([[Paragraph('LEGACY 3D STUDIO', title_style), Paragraph('CONFIRMAÇÃO DE PEDIDO', right_style)]],colWidths=[105*mm,55*mm])
    brand.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,-1),1,colors.HexColor('#7C3AED')),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
    story += [brand, Spacer(1,5*mm)]

    created=item['created_at'].strftime('%d/%m/%Y %H:%M') if item['created_at'] else '-'
    summary=[
        ['Protocolo', item['request_number'], 'Data', created],
        ['Cliente', item['name'], 'Status', 'Recebido' if item['status']=='received' else item['status']],
        ['Contato', item['email'] or item['phone'] or '-', 'Quantidade', str(item['quantity'])],
    ]
    t=Table(summary,colWidths=[25*mm,60*mm,23*mm,52*mm])
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(0,-1),colors.HexColor('#F3F4F6')),('BACKGROUND',(2,0),(2,-1),colors.HexColor('#F3F4F6')),('FONTNAME',(0,0),(-1,-1),'Helvetica'),('FONTNAME',(0,0),(0,-1),'Helvetica-Bold'),('FONTNAME',(2,0),(2,-1),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),9),('GRID',(0,0),(-1,-1),0.5,colors.HexColor('#E5E7EB')),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('PADDING',(0,0),(-1,-1),6)]))
    story += [t, Spacer(1,5*mm), Paragraph('Detalhes do pedido', h)]

    if item['request_type']=='catalog':
        currency=item['currency'] or 'USD'
        detail=[['Produto','Qtd.','Valor unitário','Total'],[item['title'],str(item['quantity']),money(item['unit_price'],currency),money(item['total_amount'],currency)]]
    else:
        detail=[['Solicitação','Qtd.','Valor'],[item['title'],str(item['quantity']),'A definir após análise']]
    dt=Table(detail,colWidths=[82*mm,20*mm,30*mm,28*mm] if item['request_type']=='catalog' else [100*mm,20*mm,40*mm])
    dt.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#111827')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTNAME',(0,1),(-1,-1),'Helvetica'),('FONTSIZE',(0,0),(-1,-1),9),('GRID',(0,0),(-1,-1),0.5,colors.HexColor('#D1D5DB')),('PADDING',(0,0),(-1,-1),7),('VALIGN',(0,0),(-1,-1),'TOP')]))
    story += [dt, Spacer(1,5*mm)]

    note=KeepTogether([
        Paragraph('Informação importante', h),
        Paragraph('Esta confirmação registra o recebimento do pedido pela Legacy 3D Studio. O início da produção e o prazo final serão confirmados após a análise do pedido. Este documento não é uma nota fiscal.', small),
        Spacer(1,8*mm),
        Paragraph('Legacy 3D Studio • legacy3dstudio.com', small),
    ])
    story.append(note)
    doc.build(story)
    buf.seek(0)
    return send_file(buf,mimetype='application/pdf',as_attachment=True,download_name=f"confirmacao-{item['request_number']}.pdf")
