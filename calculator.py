from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import Blueprint, redirect, render_template, request, session, url_for

calculator_bp = Blueprint('calculator', __name__)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped


def d(value, default='0'):
    try:
        return Decimal(str(value or default))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


@calculator_bp.route('/calculator', methods=['GET', 'POST'])
@login_required
def calculator():
    result = None
    values = {
        'currency': request.form.get('currency', 'USD'),
        'filament_price': request.form.get('filament_price', ''),
        'spool_weight_g': request.form.get('spool_weight_g', '1000'),
        'grams_used': request.form.get('grams_used', ''),
        'print_hours': request.form.get('print_hours', ''),
        'machine_hourly_cost': request.form.get('machine_hourly_cost', ''),
        'electricity_cost': request.form.get('electricity_cost', '0'),
        'other_costs': request.form.get('other_costs', '0'),
        'failure_percent': request.form.get('failure_percent', '5'),
        'profit_percent': request.form.get('profit_percent', '40'),
        'quantity': request.form.get('quantity', '1'),
    }

    if request.method == 'POST':
        filament_price = d(values['filament_price'])
        spool_weight_g = d(values['spool_weight_g'], '1000')
        grams_used = d(values['grams_used'])
        print_hours = d(values['print_hours'])
        machine_hourly_cost = d(values['machine_hourly_cost'])
        electricity_cost = d(values['electricity_cost'])
        other_costs = d(values['other_costs'])
        failure_percent = d(values['failure_percent'])
        profit_percent = d(values['profit_percent'])
        quantity = max(d(values['quantity'], '1'), Decimal('1'))

        material_cost = Decimal('0') if spool_weight_g <= 0 else (filament_price / spool_weight_g) * grams_used
        machine_cost = print_hours * machine_hourly_cost
        base_cost = material_cost + machine_cost + electricity_cost + other_costs
        failure_reserve = base_cost * failure_percent / Decimal('100')
        production_cost = base_cost + failure_reserve
        total_cost = production_cost * quantity
        profit = total_cost * profit_percent / Decimal('100')
        sale_price = total_cost + profit
        unit_price = sale_price / quantity

        result = {
            'material_cost': material_cost,
            'machine_cost': machine_cost,
            'base_cost': base_cost,
            'failure_reserve': failure_reserve,
            'production_cost': production_cost,
            'total_cost': total_cost,
            'profit': profit,
            'sale_price': sale_price,
            'unit_price': unit_price,
            'currency': values['currency'],
        }

    return render_template('calculator.html', values=values, result=result)
