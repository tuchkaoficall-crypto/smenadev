"""
Финансы: платежи, выручка (комиссия) по месяцам и категориям, экспорт
"""
from collections import defaultdict
from datetime import datetime

from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required

from admin import db_session, get_or_404
from admin import services
from database.models import Payment, Order
from config import OrderStatus, ORDER_STATUS_NAMES

bp = Blueprint('finance', __name__, url_prefix='/finance')


def _payments():
    q = db_session.query(Payment)
    if request.args.get('status'):
        q = q.filter(Payment.status == request.args['status'])
    if request.args.get('type'):
        q = q.filter(Payment.payment_type == request.args['type'])
    return q.order_by(Payment.created_at.desc())


@bp.route('/')
@login_required
def index():
    payments = _payments().limit(300).all()
    orders = db_session.query(Order).all()
    closed = [o for o in orders if o.status == OrderStatus.PAYMENT_COMPLETED]

    months = defaultdict(lambda: {"commission": 0.0, "gmv": 0.0, "orders": 0})
    for o in closed:
        d = o.closed_at or o.created_at
        if not d:
            continue
        m = months[d.strftime("%Y-%m")]
        m["commission"] += o.commission or 0
        m["gmv"] += services.order_gmv(o)
        m["orders"] += 1
    month_keys = sorted(months)[-12:]

    by_category = defaultdict(float)
    for o in closed:
        by_category[o.category] += o.commission or 0

    # Ставка комиссии по заказу (для проверки сетки 5 / 10 / 12,5 %)
    tiers = defaultdict(lambda: {"orders": 0, "commission": 0.0})
    for o in orders:
        if o.status == OrderStatus.CANCELLED or not o.shift_amount:
            continue
        rate = (o.commission or 0) / (o.shift_amount * (o.workers_needed or 1)) * 100
        key = "5 %" if rate < 7.5 else ("10 %" if rate < 11.25 else "12,5 %")
        tiers[key]["orders"] += 1
        tiers[key]["commission"] += o.commission or 0

    all_payments = db_session.query(Payment).all()
    totals = {
        "earned": sum(o.commission or 0 for o in closed),
        "received": sum(p.amount for p in all_payments if p.status == "completed"),
        "pending": sum(p.amount for p in all_payments if p.status == "pending"),
        "pending_count": sum(1 for p in all_payments if p.status == "pending"),
        "pipeline": sum(o.commission or 0 for o in orders if o.status in services.ACTIVE_STATUSES),
        "gmv": sum(services.order_gmv(o) for o in closed),
    }
    # Закрытые без предоплаты / с долгом — повод проверить
    awaiting = [o for o in orders if o.status == OrderStatus.PREPAYMENT]
    return render_template(
        'finance/index.html', payments=payments, totals=totals,
        months={"labels": month_keys, "commission": [round(months[k]["commission"]) for k in month_keys],
                "gmv": [round(months[k]["gmv"]) for k in month_keys],
                "orders": [months[k]["orders"] for k in month_keys]},
        by_category=sorted(by_category.items(), key=lambda x: -x[1]),
        tiers=dict(sorted(tiers.items())), awaiting=awaiting,
        args=dict(request.args), status_names=ORDER_STATUS_NAMES,
    )


@bp.route('/payments/<int:payment_id>/paid', methods=['POST'])
@login_required
def mark_paid(payment_id):
    p = get_or_404(Payment, payment_id)
    if p.status != "pending":
        flash('Платёж уже обработан', 'warning')
        return redirect(services.safe_next(url_for('finance.index')))
    p.status = "completed"
    p.paid_at = datetime.utcnow()
    p.payment_method = (request.form.get('method') or '').strip() or p.payment_method
    p.transaction_id = (request.form.get('transaction_id') or '').strip() or p.transaction_id
    services.log_action('payment_paid', 'order', p.order_id,
                        f"{services.PAYMENT_TYPE_NAMES.get(p.payment_type, p.payment_type)} {p.amount:.0f} ₽",
                        commit=False)
    db_session.commit()
    if p.order and p.order.employer:
        from services import order_texts as T
        from services import order_keyboards as K
        services._notify(p.order.employer.user_id, T.employer_payment_confirmed(p.order, p.amount),
                         K.employer_card_rows(p.order_id))
    flash(f'Платёж #{p.id} на {p.amount:.0f} ₽ отмечен оплаченным', 'success')
    return redirect(services.safe_next(url_for('finance.index')))


@bp.route('/payments/<int:payment_id>/cancel', methods=['POST'])
@login_required
def cancel(payment_id):
    p = get_or_404(Payment, payment_id)
    if p.status == "pending":
        p.status = "cancelled"
        services.log_action('payment_cancel', 'order', p.order_id, f"Платёж #{p.id}", commit=False)
        db_session.commit()
        flash(f'Платёж #{p.id} отменён', 'warning')
    return redirect(services.safe_next(url_for('finance.index')))


@bp.route('/export.csv')
@login_required
def export_csv():
    rows = [[p.id, p.order_id, p.order.employer.company_name if p.order and p.order.employer else '',
             services.PAYMENT_TYPE_NAMES.get(p.payment_type, p.payment_type), round(p.amount, 2),
             services.PAYMENT_STATUS_NAMES.get(p.status, p.status), p.payment_method or '',
             p.transaction_id or '', services.fmt_dt(p.created_at), services.fmt_dt(p.paid_at), p.comment or '']
            for p in _payments().all()]
    return services.csv_response(
        f"payments_{datetime.now():%Y%m%d_%H%M}.csv",
        ["ID", "Заказ", "Компания", "Тип", "Сумма", "Статус", "Способ", "Транзакция", "Создан", "Оплачен", "Комментарий"],
        rows,
    )
