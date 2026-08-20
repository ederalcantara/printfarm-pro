import os
from functools import wraps

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

machine_admin_bp = Blueprint('machine_admin', __name__)
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


@machine_admin_bp.get('/machines/manage')
@login_required
def manage():
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute('''
                SELECT m.*,
                       (SELECT COUNT(*) FROM print_jobs j WHERE j.machine_id=m.id) AS job_count,
                       EXISTS(SELECT 1 FROM print_jobs j WHERE j.machine_id=m.id AND j.status='printing') AS is_printing
                FROM machines m
                ORDER BY CASE m.status WHEN 'printing' THEN 0 WHEN 'available' THEN 1 WHEN 'maintenance' THEN 2 ELSE 3 END, m.name
            ''')
            machines = cur.fetchall()
    except psycopg2.errors.UndefinedTable:
        c.rollback()
        with c.cursor() as cur:
            cur.execute('SELECT m.*, 0 AS job_count, FALSE AS is_printing FROM machines m ORDER BY m.name')
            machines = cur.fetchall()
    finally:
        c.close()
    return render_template('machines_manage.html', machines=machines)


@machine_admin_bp.post('/machines/<int:machine_id>/edit')
@login_required
def edit(machine_id):
    name = request.form.get('name','').strip()
    if not name:
        flash('Nome da máquina é obrigatório.', 'danger')
        return redirect(url_for('machine_admin.manage'))
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT status FROM machines WHERE id=%s FOR UPDATE', (machine_id,))
            current = cur.fetchone()
            if not current:
                flash('Máquina não encontrada.', 'danger')
                return redirect(url_for('machine_admin.manage'))
            requested_status = request.form.get('status','available')
            if current['status'] == 'printing' and requested_status != 'printing':
                cur.execute("SELECT COUNT(*) AS n FROM print_jobs WHERE machine_id=%s AND status='printing'", (machine_id,))
                if cur.fetchone()['n']:
                    flash('Finalize a impressão atual antes de mudar o status desta máquina.', 'danger')
                    return redirect(url_for('machine_admin.manage'))
            cur.execute('''UPDATE machines SET name=%s, model=%s, status=%s, hourly_cost=%s, currency=%s, notes=%s WHERE id=%s''',
                        (name, request.form.get('model'), requested_status, request.form.get('hourly_cost') or 0,
                         request.form.get('currency','USD'), request.form.get('notes'), machine_id))
        c.commit()
    finally:
        c.close()
    flash('Máquina atualizada.', 'success')
    return redirect(url_for('machine_admin.manage'))


@machine_admin_bp.post('/machines/<int:machine_id>/remove')
@login_required
def remove(machine_id):
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT * FROM machines WHERE id=%s FOR UPDATE', (machine_id,))
            machine = cur.fetchone()
            if not machine:
                flash('Máquina não encontrada.', 'danger')
                return redirect(url_for('machine_admin.manage'))
            try:
                cur.execute("SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE status='printing') AS active FROM print_jobs WHERE machine_id=%s", (machine_id,))
                usage = cur.fetchone()
            except psycopg2.errors.UndefinedTable:
                c.rollback()
                usage = {'total': 0, 'active': 0}
                with c.cursor() as cur2:
                    cur2.execute('SELECT * FROM machines WHERE id=%s FOR UPDATE', (machine_id,))
                    machine = cur2.fetchone()
            if usage['active']:
                flash('Esta máquina está imprimindo. Finalize o trabalho antes de removê-la.', 'danger')
                return redirect(url_for('machine_admin.manage'))
            if usage['total']:
                cur.execute("UPDATE machines SET status='retired' WHERE id=%s", (machine_id,))
                c.commit()
                flash('Máquina arquivada. O histórico das impressões foi preservado.', 'success')
            else:
                cur.execute('DELETE FROM machines WHERE id=%s', (machine_id,))
                c.commit()
                flash('Máquina excluída.', 'success')
    finally:
        c.close()
    return redirect(url_for('machine_admin.manage'))
