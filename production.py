import os
from functools import wraps

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app import transition_quote

production_bp = Blueprint('production', __name__)
DATABASE_URL = os.getenv('DATABASE_URL')

SCHEMA = '''
CREATE TABLE IF NOT EXISTS print_jobs (
 id SERIAL PRIMARY KEY,
 quote_id INTEGER UNIQUE NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
 project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
 machine_id INTEGER REFERENCES machines(id) ON DELETE SET NULL,
 filament_id INTEGER REFERENCES filaments(id) ON DELETE SET NULL,
 estimated_grams NUMERIC(12,2) NOT NULL DEFAULT 0,
 actual_grams NUMERIC(12,2),
 status VARCHAR(30) NOT NULL DEFAULT 'queued',
 started_at TIMESTAMPTZ,
 completed_at TIMESTAMPTZ,
 notes TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
'''


def db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def ensure():
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute(SCHEMA)
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


@production_bp.get('/printing')
@login_required
def printing_board():
    ensure()
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute('''
                SELECT q.id AS quote_id, q.quote_number, q.title, q.status AS quote_status,
                       q.estimated_grams, q.filament_id,
                       c.name AS customer_name,
                       p.id AS project_id, p.name AS project_name,
                       j.id AS job_id, j.machine_id, j.status AS job_status,
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
            cur.execute("SELECT * FROM filaments ORDER BY material,color")
            filaments = cur.fetchall()
    finally:
        c.close()
    return render_template('printing.html', jobs=jobs, machines=machines, filaments=filaments)


@production_bp.post('/printing/<int:quote_id>/start')
@login_required
def start_print(quote_id):
    ensure()
    machine_id = request.form.get('machine_id') or None
    filament_id = request.form.get('filament_id') or None
    estimated_grams = request.form.get('estimated_grams') or '0'
    if not machine_id or not filament_id:
        flash('Escolha a máquina e o filamento antes de iniciar.', 'danger')
        return redirect(url_for('production.printing_board'))

    c = db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT * FROM machines WHERE id=%s FOR UPDATE', (machine_id,))
            machine = cur.fetchone()
            if not machine:
                flash('Máquina não encontrada.', 'danger')
                return redirect(url_for('production.printing_board'))
            if machine['status'] not in ('available', 'disponivel', 'disponível'):
                flash('Essa máquina não está disponível.', 'danger')
                return redirect(url_for('production.printing_board'))
            cur.execute('UPDATE quotes SET filament_id=%s, estimated_grams=%s WHERE id=%s', (filament_id, estimated_grams, quote_id))
            cur.execute('SELECT id FROM projects WHERE quote_id=%s ORDER BY id LIMIT 1', (quote_id,))
            project = cur.fetchone()
            project_id = project['id'] if project else None
            cur.execute('''
                INSERT INTO print_jobs (quote_id,project_id,machine_id,filament_id,estimated_grams,status)
                VALUES (%s,%s,%s,%s,%s,'queued')
                ON CONFLICT (quote_id) DO UPDATE SET machine_id=EXCLUDED.machine_id, filament_id=EXCLUDED.filament_id,
                    estimated_grams=EXCLUDED.estimated_grams, project_id=EXCLUDED.project_id
            ''', (quote_id, project_id, machine_id, filament_id, estimated_grams))
        c.commit()
    finally:
        c.close()

    try:
        transition_quote(quote_id, 'printing')
    except ValueError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('production.printing_board'))

    c = db()
    try:
        with c.cursor() as cur:
            cur.execute("UPDATE machines SET status='printing' WHERE id=%s", (machine_id,))
            cur.execute("UPDATE print_jobs SET status='printing', started_at=NOW() WHERE quote_id=%s", (quote_id,))
        c.commit()
    finally:
        c.close()
    flash('Impressão iniciada. O filamento estimado foi baixado do estoque.', 'success')
    return redirect(url_for('production.printing_board'))


@production_bp.post('/printing/<int:quote_id>/complete')
@login_required
def complete_print(quote_id):
    ensure()
    actual_grams = request.form.get('actual_grams')
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT machine_id FROM print_jobs WHERE quote_id=%s', (quote_id,))
            job = cur.fetchone()
    finally:
        c.close()

    try:
        transition_quote(quote_id, 'completed', actual_grams)
    except ValueError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('production.printing_board'))

    c = db()
    try:
        with c.cursor() as cur:
            cur.execute("UPDATE print_jobs SET status='completed', actual_grams=%s, completed_at=NOW() WHERE quote_id=%s", (actual_grams or None, quote_id))
            if job and job['machine_id']:
                cur.execute("UPDATE machines SET status='available' WHERE id=%s", (job['machine_id'],))
        c.commit()
    finally:
        c.close()
    flash('Impressão concluída. O estoque foi ajustado pelo consumo real e a máquina foi liberada.', 'success')
    return redirect(url_for('production.printing_board'))
