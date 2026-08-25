import os
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from functools import wraps

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, flash, g, redirect, request, session, url_for

multicolor_stock_bp = Blueprint('multicolor_stock', __name__)
DATABASE_URL = os.getenv('DATABASE_URL')
MIN_TOTAL_GRAMS_PER_UNIT = Decimal('1.00')
MIN_MATERIAL_GRAMS_PER_UNIT = Decimal('0.01')


def db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def d(value, default='0'):
    try:
        return Decimal(str(value if value not in (None, '') else default))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped


def _batch_materials(batch_id):
    cache = getattr(g, '_batch_material_cache', None)
    if cache is None:
        cache = {}
        g._batch_material_cache = cache
    if batch_id in cache:
        return cache[batch_id]
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute('''SELECT m.id,m.batch_id,m.filament_id,m.grams_per_unit,m.reserved_g,m.consumed_g,
                                  f.brand,f.material,f.color,f.remaining_g,f.reserved_g AS filament_reserved_g,
                                  GREATEST(f.remaining_g-f.reserved_g,0) AS available_g
                           FROM production_batch_materials m
                           JOIN filaments f ON f.id=m.filament_id
                           WHERE m.batch_id=%s ORDER BY m.id''', (batch_id,))
            rows = cur.fetchall()
    finally:
        c.close()
    cache[batch_id] = rows
    return rows


@multicolor_stock_bp.app_context_processor
def multicolor_template_helpers():
    return {'batch_materials': _batch_materials}


def _parse_materials(product):
    filament_ids = request.form.getlist('material_filament_id')
    grams_values = request.form.getlist('material_grams_per_unit')

    # Compatibilidade com formulários antigos e testes existentes.
    if not filament_ids and not grams_values:
        filament_ids = [request.form.get('filament_id') or product.get('filament_id')]
        grams_values = [request.form.get('grams_per_unit') or product.get('grams_per_unit')]

    merged = defaultdict(Decimal)
    for index in range(max(len(filament_ids), len(grams_values))):
        filament_id = filament_ids[index] if index < len(filament_ids) else ''
        raw_grams = grams_values[index] if index < len(grams_values) else ''
        if not filament_id and not raw_grams:
            continue
        if not filament_id and index == 0:
            filament_id = product.get('filament_id')
        grams = d(raw_grams)
        if not filament_id:
            raise ValueError('Escolha um filamento para cada cor/material.')
        if grams < MIN_MATERIAL_GRAMS_PER_UNIT:
            raise ValueError('Cada cor/material precisa ter consumo maior que zero.')
        merged[int(filament_id)] += grams

    materials = [{'filament_id': fid, 'grams_per_unit': grams} for fid, grams in merged.items()]
    total_per_unit = sum((m['grams_per_unit'] for m in materials), Decimal('0'))
    if not materials:
        raise ValueError('Adicione pelo menos um filamento à produção.')
    if total_per_unit < MIN_TOTAL_GRAMS_PER_UNIT:
        raise ValueError(f'O peso total da peça é {total_per_unit} g/unidade. A produção foi bloqueada porque o total deve ser pelo menos 1,00 g.')
    return materials, total_per_unit


@multicolor_stock_bp.post('/production/stock/create-multicolor')
@login_required
def create_batch():
    product_id = request.form.get('product_id')
    try:
        quantity = max(int(request.form.get('quantity') or 1), 1)
    except ValueError:
        quantity = 1

    c = db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT * FROM products WHERE id=%s FOR UPDATE', (product_id,))
            product = cur.fetchone()
            if not product:
                flash('Produto não encontrado.', 'danger')
                return redirect(url_for('operations.stock_production'))
            try:
                materials, total_per_unit = _parse_materials(product)
            except ValueError as exc:
                flash(str(exc), 'danger')
                return redirect(url_for('operations.stock_production'))

            filament_rows = {}
            for filament_id in sorted(m['filament_id'] for m in materials):
                cur.execute('SELECT * FROM filaments WHERE id=%s FOR UPDATE', (filament_id,))
                filament = cur.fetchone()
                if not filament:
                    flash('Um dos filamentos selecionados não foi encontrado.', 'danger')
                    return redirect(url_for('operations.stock_production'))
                filament_rows[filament_id] = filament

            for material in materials:
                filament = filament_rows[material['filament_id']]
                reserve = material['grams_per_unit'] * quantity
                available = d(filament['remaining_g']) - d(filament['reserved_g'])
                if available < reserve:
                    label = f"{filament['material']} {filament['color']}"
                    flash(f'{label}: necessário {reserve} g; disponível {available} g.', 'danger')
                    return redirect(url_for('operations.stock_production'))
                material['reserved_g'] = reserve

            first = materials[0]
            total_reserved = sum((m['reserved_g'] for m in materials), Decimal('0'))
            cur.execute('''INSERT INTO production_batches(product_id,filament_id,mode,quantity,grams_per_unit,reserved_g,status,notes)
                           VALUES(%s,%s,'stock',%s,%s,%s,'queued',%s) RETURNING id''',
                        (product_id, first['filament_id'], quantity, total_per_unit, total_reserved, request.form.get('notes')))
            batch_id = cur.fetchone()['id']

            for material in materials:
                cur.execute('UPDATE filaments SET reserved_g=reserved_g+%s WHERE id=%s',
                            (material['reserved_g'], material['filament_id']))
                cur.execute('''INSERT INTO production_batch_materials(batch_id,filament_id,grams_per_unit,reserved_g)
                               VALUES(%s,%s,%s,%s)''',
                            (batch_id, material['filament_id'], material['grams_per_unit'], material['reserved_g']))
                cur.execute('''INSERT INTO inventory_movements(filament_id,product_id,grams,movement_type,reference_type,reference_id,notes,filament_g)
                               VALUES(%s,%s,0,'filament_reserved','production_batch',%s,%s,%s)''',
                            (material['filament_id'], product_id, batch_id,
                             f"Reservados {material['reserved_g']} g para lote #{batch_id}", material['reserved_g']))
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

    flash(f'Lote #{batch_id} criado com {len(materials)} cor(es)/material(is). Total reservado: {total_reserved} g.', 'success')
    return redirect(url_for('operations.stock_production'))


@multicolor_stock_bp.post('/production/stock/<int:batch_id>/complete-multicolor')
@login_required
def complete_batch(batch_id):
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT * FROM production_batches WHERE id=%s FOR UPDATE', (batch_id,))
            batch = cur.fetchone()
            if not batch or batch['status'] not in ('queued', 'printing'):
                flash('Lote não encontrado ou já encerrado.', 'danger')
                return redirect(url_for('operations.stock_production'))

            cur.execute('''SELECT m.*,f.material,f.color FROM production_batch_materials m
                           JOIN filaments f ON f.id=m.filament_id
                           WHERE m.batch_id=%s ORDER BY m.id FOR UPDATE OF m''', (batch_id,))
            materials = cur.fetchall()
            if not materials:
                flash('Lote sem materiais registrados. Não foi possível concluir com segurança.', 'danger')
                return redirect(url_for('operations.stock_production'))

            filament_rows = {}
            for filament_id in sorted({m['filament_id'] for m in materials}):
                cur.execute('SELECT * FROM filaments WHERE id=%s FOR UPDATE', (filament_id,))
                filament_rows[filament_id] = cur.fetchone()

            actuals = []
            for material in materials:
                raw = request.form.get(f"actual_material_{material['id']}")
                actual = d(raw) if raw not in (None, '') else d(material['reserved_g'])
                if actual < MIN_MATERIAL_GRAMS_PER_UNIT:
                    flash(f"{material['material']} {material['color']}: informe um consumo real maior que zero.", 'danger')
                    return redirect(url_for('operations.stock_production'))
                filament = filament_rows[material['filament_id']]
                extra = max(Decimal('0'), actual - d(material['reserved_g']))
                available_unreserved = d(filament['remaining_g']) - d(filament['reserved_g'])
                if extra > available_unreserved:
                    flash(f"{material['material']} {material['color']}: estoque insuficiente para o consumo real informado.", 'danger')
                    return redirect(url_for('operations.stock_production'))
                actuals.append((material, actual))

            total_actual = Decimal('0')
            for material, actual in actuals:
                reserved = d(material['reserved_g'])
                cur.execute('''UPDATE filaments
                               SET reserved_g=GREATEST(0,reserved_g-%s), remaining_g=remaining_g-%s
                               WHERE id=%s''', (reserved, actual, material['filament_id']))
                cur.execute('UPDATE production_batch_materials SET consumed_g=%s WHERE id=%s', (actual, material['id']))
                cur.execute('''INSERT INTO inventory_movements(filament_id,product_id,grams,movement_type,reference_type,reference_id,notes,product_qty,filament_g)
                               VALUES(%s,%s,%s,'stock_production','production_batch',%s,%s,0,%s)''',
                            (material['filament_id'], batch['product_id'], -actual, batch_id,
                             f"Consumo do lote #{batch_id}", -actual))
                total_actual += actual

            cur.execute('UPDATE products SET stock_qty=stock_qty+%s WHERE id=%s', (batch['quantity'], batch['product_id']))
            cur.execute("UPDATE production_batches SET status='completed',consumed_g=%s,completed_at=NOW() WHERE id=%s",
                        (total_actual, batch_id))
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

    flash(f'Lote #{batch_id} concluído. Consumo total: {total_actual} g; {batch["quantity"]} peça(s) adicionada(s) ao estoque.', 'success')
    return redirect(url_for('operations.stock_production'))


@multicolor_stock_bp.post('/production/stock/<int:batch_id>/cancel-multicolor')
@login_required
def cancel_batch(batch_id):
    c = db()
    released = Decimal('0')
    try:
        with c.cursor() as cur:
            cur.execute('SELECT * FROM production_batches WHERE id=%s FOR UPDATE', (batch_id,))
            batch = cur.fetchone()
            if not batch or batch['status'] not in ('queued', 'printing'):
                flash('Lote não encontrado ou já encerrado.', 'danger')
                return redirect(url_for('operations.stock_production'))
            cur.execute('SELECT * FROM production_batch_materials WHERE batch_id=%s ORDER BY filament_id FOR UPDATE', (batch_id,))
            materials = cur.fetchall()
            for material in materials:
                cur.execute('SELECT id FROM filaments WHERE id=%s FOR UPDATE', (material['filament_id'],))
                reserve = d(material['reserved_g'])
                cur.execute('UPDATE filaments SET reserved_g=GREATEST(0,reserved_g-%s) WHERE id=%s',
                            (reserve, material['filament_id']))
                released += reserve
            cur.execute("UPDATE production_batches SET status='cancelled' WHERE id=%s", (batch_id,))
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
    flash(f'Lote #{batch_id} cancelado. {released} g de reservas foram liberados.', 'success')
    return redirect(url_for('operations.stock_production'))


@multicolor_stock_bp.post('/production/stock/<int:batch_id>/invalidate')
@login_required
def invalidate_batch(batch_id):
    c = db()
    restored = Decimal('0')
    try:
        with c.cursor() as cur:
            cur.execute('SELECT * FROM production_batches WHERE id=%s FOR UPDATE', (batch_id,))
            batch = cur.fetchone()
            if not batch or batch['status'] != 'completed' or not batch.get('invalid_reason'):
                flash('Somente lotes concluídos já marcados como inválidos podem ser revertidos por esta ação.', 'danger')
                return redirect(url_for('operations.stock_production'))

            cur.execute('SELECT * FROM products WHERE id=%s FOR UPDATE', (batch['product_id'],))
            product = cur.fetchone()
            physical = int(product['stock_qty'] or 0)
            product_reserved = int(product.get('reserved_stock_qty') or 0)
            qty = int(batch['quantity'] or 0)
            if physical - qty < product_reserved:
                flash('Não é possível reverter este lote porque parte do estoque pronto já está reservada para pedidos.', 'danger')
                return redirect(url_for('operations.stock_production'))

            cur.execute('SELECT * FROM production_batch_materials WHERE batch_id=%s ORDER BY filament_id FOR UPDATE', (batch_id,))
            materials = cur.fetchall()
            for material in materials:
                consumed = d(material['consumed_g'])
                if consumed <= 0:
                    continue
                cur.execute('SELECT id FROM filaments WHERE id=%s FOR UPDATE', (material['filament_id'],))
                cur.execute('UPDATE filaments SET remaining_g=remaining_g+%s WHERE id=%s',
                            (consumed, material['filament_id']))
                cur.execute('''INSERT INTO inventory_movements(filament_id,product_id,grams,movement_type,reference_type,reference_id,notes,product_qty,filament_g)
                               VALUES(%s,%s,%s,'stock_production_reversal','production_batch',%s,%s,0,%s)''',
                            (material['filament_id'], batch['product_id'], consumed, batch_id,
                             f"Reversão do lote inválido #{batch_id}", consumed))
                restored += consumed

            cur.execute('UPDATE products SET stock_qty=stock_qty-%s WHERE id=%s', (qty, batch['product_id']))
            reason = request.form.get('reason') or batch['invalid_reason'] or 'Lote inválido revertido.'
            cur.execute("UPDATE production_batches SET status='invalidated',invalidated_at=NOW(),invalid_reason=%s WHERE id=%s",
                        (reason, batch_id))
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
    flash(f'Lote #{batch_id} invalidado e revertido. {qty} peça(s) removida(s) do estoque e {restored} g devolvidos ao filamento.', 'success')
    return redirect(url_for('operations.stock_production'))
