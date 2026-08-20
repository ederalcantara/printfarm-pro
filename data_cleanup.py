import os
from functools import wraps
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

cleanup_bp = Blueprint('cleanup', __name__)
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

@cleanup_bp.route('/admin/cleanup', methods=['GET','POST'])
@login_required
def cleanup():
    if request.method == 'POST':
        if request.form.get('confirmation','').strip().upper() != 'APAGAR':
            flash('Digite APAGAR para confirmar a limpeza.', 'danger')
            return redirect(url_for('cleanup.cleanup'))
        c=db()
        try:
            with c.cursor() as cur:
                # Restore filament consumed by test print jobs before deleting them.
                cur.execute("""UPDATE filaments f SET current_weight_g=f.current_weight_g+x.grams FROM (SELECT filament_id,SUM(COALESCE(actual_grams,estimated_grams,0)) grams FROM print_jobs WHERE filament_id IS NOT NULL AND status IN ('printing','completed') GROUP BY filament_id) x WHERE f.id=x.filament_id""")
                cur.execute("UPDATE machines SET status='idle' WHERE status='printing'")
                cur.execute('DELETE FROM print_jobs')
                cur.execute('DELETE FROM quote_public_links')
                cur.execute('DELETE FROM quote_items')
                cur.execute('DELETE FROM projects')
                cur.execute('DELETE FROM quotes')
                cur.execute('DELETE FROM customer_request_files')
                cur.execute('DELETE FROM customer_requests')
                cur.execute('DELETE FROM customers')
            c.commit()
        except Exception:
            c.rollback(); raise
        finally:
            c.close()
        flash('Dados de teste apagados. Máquinas, filamentos, catálogo e configurações foram preservados.', 'success')
        return redirect(url_for('dashboard'))
    return render_template('data_cleanup.html')
