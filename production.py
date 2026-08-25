import os
from decimal import Decimal
from functools import wraps

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app import transition_quote

production_bp = Blueprint('production', __name__)
DATABASE_URL = os.getenv('DATABASE_URL')


def db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def ensure():
    # Managed by migration_runner.py at application startup.
    return


def d(value):
    try:return Decimal(str(value or 0))
    except Exception:return Decimal('0')


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped


@production_bp.get('/printing')
@login_required
def printing_board():
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute('''
                SELECT q.id AS quote_id, q.quote_number, q.title, q.status AS quote_status,
                       q.estimated_grams, q.filament_id,
                       c.name AS customer_name,
                       p.id AS project_id, p.name AS project_name,
                       j.id AS job_id, j.machine_id, j.status AS job_status, j.reserved_g,
                       j.started_at, j.completed_at, j.actual_grams,
                       m.name AS machine_name, m.model AS machine_model,
                       f.material AS filament_material, f.color AS filament_color
                FROM quotes q
                LEFT JOIN customers c ON c.id=q.customer_id
                LEFT JOIN projects p ON p.quote_id=q.id
                LEFT JOIN print_jobs j ON j.quote_id=q.id
                LEFT JOIN machines m ON m.id=j.machine_id
                LEFT JOIN filaments f ON f.id=COALESCE(j.filament_id,q.filament_id)
                WHERE q.status IN ('execution','printing','completed')
                ORDER BY CASE q.status WHEN 'printing' THEN 0 WHEN 'execution' THEN 1 ELSE 2 END, q.updated_at DESC
            ''')
            jobs = cur.fetchall()
            cur.execute("SELECT * FROM machines ORDER BY CASE status WHEN 'available' THEN 0 ELSE 1 END, name")
            machines = cur.fetchall()
            cur.execute("SELECT *, (remaining_g-reserved_g) AS available_g FROM filaments ORDER BY material,color")
            filaments = cur.fetchall()
    finally:
        c.close()
    return render_template('printing.html', jobs=jobs, machines=machines, filaments=filaments)


@production_bp.post('/printing/<int:quote_id>/queue')
@login_required
def queue_print(quote_id):
    filament_id=request.form.get('filament_id') or None
    estimated=d(request.form.get('estimated_grams'))
    if not filament_id or estimated<=0:
        flash('Escolha o filamento e informe o consumo estimado.','danger')
        return redirect(url_for('production.printing_board'))
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT * FROM quotes WHERE id=%s FOR UPDATE',(quote_id,));quote=cur.fetchone()
            if not quote or quote['status']!='execution':
                flash('O pedido precisa estar em execução para entrar na fila.','danger');return redirect(url_for('production.printing_board'))
            cur.execute('SELECT * FROM print_jobs WHERE quote_id=%s FOR UPDATE',(quote_id,));old=cur.fetchone()
            if old and old['reserved_g']:
                cur.execute('UPDATE filaments SET reserved_g=GREATEST(0,reserved_g-%s) WHERE id=%s',(old['reserved_g'],old['filament_id']))
            cur.execute('SELECT * FROM filaments WHERE id=%s FOR UPDATE',(filament_id,));filament=cur.fetchone()
            available=d(filament['remaining_g'])-d(filament['reserved_g']) if filament else Decimal('0')
            if not filament or available<estimated:
                if old and old['reserved_g']:
                    cur.execute('UPDATE filaments SET reserved_g=reserved_g+%s WHERE id=%s',(old['reserved_g'],old['filament_id']))
                flash(f'Filamento insuficiente. Necessário {estimated} g; disponível {available} g.','danger');return redirect(url_for('production.printing_board'))
            cur.execute('UPDATE filaments SET reserved_g=reserved_g+%s WHERE id=%s',(estimated,filament_id))
            cur.execute('SELECT id FROM projects WHERE quote_id=%s ORDER BY id LIMIT 1',(quote_id,));project=cur.fetchone();project_id=project['id'] if project else None
            cur.execute('''INSERT INTO print_jobs(quote_id,project_id,filament_id,estimated_grams,reserved_g,status)
                           VALUES(%s,%s,%s,%s,%s,'queued')
                           ON CONFLICT(quote_id) DO UPDATE SET project_id=EXCLUDED.project_id,filament_id=EXCLUDED.filament_id,
                           estimated_grams=EXCLUDED.estimated_grams,reserved_g=EXCLUDED.reserved_g,status='queued',machine_id=NULL''',(quote_id,project_id,filament_id,estimated,estimated))
            cur.execute('UPDATE quotes SET filament_id=%s,estimated_grams=%s WHERE id=%s',(filament_id,estimated,quote_id))
            cur.execute("INSERT INTO inventory_movements(filament_id,grams,movement_type,reference_type,reference_id,notes,filament_g) VALUES(%s,0,'filament_reserved','quote',%s,%s,%s)",(filament_id,quote_id,f'Reservado para {quote["quote_number"]}',estimated))
            cur.execute("INSERT INTO order_events(quote_id,event_type,details) VALUES(%s,'production_queued',%s)",(quote_id,f'{estimated} g reservados'))
        c.commit()
    except Exception:c.rollback();raise
    finally:c.close()
    flash('Pedido entrou na fila e o filamento foi reservado.','success')
    return redirect(url_for('production.printing_board'))


@production_bp.post('/printing/<int:quote_id>/unqueue')
@login_required
def unqueue_print(quote_id):
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT * FROM print_jobs WHERE quote_id=%s FOR UPDATE',(quote_id,));job=cur.fetchone()
            if job and job['status']=='queued':
                cur.execute('UPDATE filaments SET reserved_g=GREATEST(0,reserved_g-%s) WHERE id=%s',(job['reserved_g'],job['filament_id']))
                cur.execute('DELETE FROM print_jobs WHERE quote_id=%s',(quote_id,))
                cur.execute("INSERT INTO order_events(quote_id,event_type,details) VALUES(%s,'production_unqueued','Reserva de filamento liberada')",(quote_id,))
        c.commit()
    finally:c.close()
    flash('Pedido retirado da fila; reserva liberada.','success')
    return redirect(url_for('production.printing_board'))


@production_bp.post('/printing/<int:quote_id>/start')
@login_required
def start_print(quote_id):
    machine_id=request.form.get('machine_id') or None
    if not machine_id:
        flash('Escolha a máquina antes de iniciar.','danger');return redirect(url_for('production.printing_board'))
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT * FROM machines WHERE id=%s FOR UPDATE',(machine_id,));machine=cur.fetchone()
            if not machine or machine['status'] not in ('available','disponivel','disponível'):
                flash('Essa máquina não está disponível.','danger');return redirect(url_for('production.printing_board'))
            cur.execute('SELECT * FROM print_jobs WHERE quote_id=%s FOR UPDATE',(quote_id,));job=cur.fetchone()
            if not job or job['status']!='queued' or d(job['reserved_g'])<=0:
                flash('Primeiro coloque o pedido na fila para reservar o filamento.','danger');return redirect(url_for('production.printing_board'))
            cur.execute('SELECT * FROM filaments WHERE id=%s FOR UPDATE',(job['filament_id'],));filament=cur.fetchone()
            reserved=d(job['reserved_g'])
            if not filament or d(filament['remaining_g'])<reserved:
                flash('O estoque físico de filamento não cobre a reserva.','danger');return redirect(url_for('production.printing_board'))
            cur.execute('UPDATE filaments SET reserved_g=GREATEST(0,reserved_g-%s),remaining_g=remaining_g-%s WHERE id=%s',(reserved,reserved,job['filament_id']))
            cur.execute('UPDATE quotes SET stock_deducted=TRUE,stock_deducted_at=NOW() WHERE id=%s',(quote_id,))
            cur.execute("UPDATE machines SET status='printing' WHERE id=%s",(machine_id,))
            cur.execute("UPDATE print_jobs SET machine_id=%s,status='printing',started_at=NOW() WHERE quote_id=%s",(machine_id,quote_id))
            cur.execute("INSERT INTO inventory_movements(filament_id,grams,movement_type,reference_type,reference_id,notes,filament_g) VALUES(%s,%s,'print_start','quote',%s,'Reserva convertida em consumo',%s)",(job['filament_id'],-reserved,quote_id,-reserved))
        c.commit()
    except Exception:c.rollback();raise
    finally:c.close()
    try:
        transition_quote(quote_id,'printing')
    except ValueError as exc:
        flash(str(exc),'danger');return redirect(url_for('production.printing_board'))
    flash('Impressão iniciada; a reserva virou consumo físico.','success')
    return redirect(url_for('production.printing_board'))


@production_bp.post('/printing/<int:quote_id>/complete')
@login_required
def complete_print(quote_id):
    actual_grams=request.form.get('actual_grams')
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT machine_id FROM print_jobs WHERE quote_id=%s',(quote_id,));job=cur.fetchone()
    finally:c.close()
    try:
        transition_quote(quote_id,'completed',actual_grams)
    except ValueError as exc:
        flash(str(exc),'danger');return redirect(url_for('production.printing_board'))
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute("UPDATE print_jobs SET status='completed',actual_grams=%s,reserved_g=0,completed_at=NOW() WHERE quote_id=%s",(actual_grams or None,quote_id))
            if job and job['machine_id']:cur.execute("UPDATE machines SET status='available' WHERE id=%s",(job['machine_id'],))
            cur.execute("INSERT INTO order_events(quote_id,event_type,details) VALUES(%s,'production_completed',%s)",(quote_id,f'Consumo real: {actual_grams or 0} g'))
        c.commit()
    finally:c.close()
    flash('Impressão concluída; estoque ajustado pelo consumo real.','success')
    return redirect(url_for('production.printing_board'))
