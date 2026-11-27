"""
Управление заказами: фильтры, CSV, карточка с конвейером статусов,
действия по жизненному циклу и работа с откликами
"""
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required
from sqlalchemy import or_

from admin import db_session, get_or_404
from admin import services, growth
from admin.services import LifecycleError
from database.models import Order, Response, Employer
from config import ORDER_STATUS_NAMES, JOB_CATEGORIES

bp = Blueprint('orders', __name__, url_prefix='/orders')

SORTS = {
    "new": Order.created_at.desc(),
    "old": Order.created_at.asc(),
    "shift": Order.shift_date.asc(),
    "shift_desc": Order.shift_date.desc(),
    "pay": Order.payment_amount.desc(),
}


def _filtered_query():
    args = request.args
    query = db_session.query(Order).join(Employer, Order.employer_id == Employer.id)
    status = args.get('status')
    if status == 'active':
        query = query.filter(Order.status.in_(services.ACTIVE_STATUSES))
    elif status == 'moderation':
        query = query.filter(Order.status.in_(services.MODERATION_STATUSES))
    elif status:
        query = query.filter(Order.status == status)
    if args.get('category'):
        query = query.filter(Order.category == args['category'])
    if args.get('city'):
        query = query.filter(Order.city == args['city'])
    if args.get('employer_id', type=int):
        query = query.filter(Order.employer_id == args.get('employer_id', type=int))
    q = (args.get('q') or '').strip()
    if q:
        like = f"%{q}%"
        conds = [Order.address.ilike(like), Order.description.ilike(like),
                 Employer.company_name.ilike(like), Order.category.ilike(like)]
        if q.lstrip('#').isdigit():
            conds.append(Order.id == int(q.lstrip('#')))
        query = query.filter(or_(*conds))
    for field, op in (('date_from', '>='), ('date_to', '<')):
        val = args.get(field)
        if val:
            try:
                d = datetime.strptime(val, '%Y-%m-%d')
            except ValueError:
                continue
            query = query.filter(Order.shift_date >= d) if op == '>=' else \
                query.filter(Order.shift_date < d + timedelta(days=1))
    return query.order_by(SORTS.get(args.get('sort'), SORTS['new']))


@bp.route('/')
@login_required
def index():
    page = request.args.get('page', 1, type=int)
    per_page = 25
    query = _filtered_query()
    total = query.count()
    orders = query.offset((page - 1) * per_page).limit(per_page).all()
    all_filtered = query.all() if total <= 2000 else []
    summary = {
        "gmv": sum(services.order_gmv(o) for o in all_filtered),
        "commission": sum(o.commission or 0 for o in all_filtered),
        "workers": sum(o.workers_needed or 0 for o in all_filtered),
    }
    cities = growth.all_city_names()
    args = {k: v for k, v in request.args.items() if k != 'page'}
    return render_template(
        'orders/index.html',
        orders=orders, page=page, total=total, total_pages=(total + per_page - 1) // per_page,
        status=request.args.get('status'), status_names=ORDER_STATUS_NAMES,
        categories=JOB_CATEGORIES, cities=cities, args=args, summary=summary,
    )


@bp.route('/export.csv')
@login_required
def export_csv():
    rows = []
    for o in _filtered_query().all():
        rows.append([
            o.id, o.employer.company_name if o.employer else '', o.category, o.city, o.address,
            services.fmt_dt(o.shift_date), o.shift_duration, o.workers_needed,
            services.confirmed_count(o), o.payment_type, o.payment_amount,
            round(services.order_gmv(o), 2), round(o.commission or 0, 2),
            round(o.prepayment_amount or 0, 2), round(services.paid_total(o), 2),
            ORDER_STATUS_NAMES.get(o.status, o.status), services.fmt_dt(o.created_at),
            services.fmt_dt(o.closed_at),
        ])
    return services.csv_response(
        f"orders_{datetime.now():%Y%m%d_%H%M}.csv",
        ["ID", "Компания", "Категория", "Город", "Адрес", "Начало смены", "Часов", "Нужно",
         "Подтверждено", "Тип оплаты", "Ставка", "ФОТ", "Комиссия", "Предоплата", "Оплачено",
         "Статус", "Создан", "Закрыт"],
        rows,
    )


@bp.route('/<int:order_id>')
@login_required
def detail(order_id):
    order = get_or_404(Order, order_id)
    responses = db_session.query(Response).filter(
        Response.order_id == order_id
    ).order_by(Response.created_at.desc()).all()
    return render_template(
        'orders/detail.html',
        order=order, responses=responses,
        status_names=ORDER_STATUS_NAMES,
        pipeline=services.PIPELINE, pipeline_index=services.PIPELINE_INDEX,
        actions=services.next_actions(order),
        confirmed=services.confirmed_count(order),
        gmv=services.order_gmv(order), paid=services.paid_total(order),
        prepayment_due=services.prepayment_due(order),
        history=services.entity_history('order', order.id),
        checkins={c.response_id: c for c in growth.order_checkins(order)},
        rel=growth.reliability_map([r.worker for r in responses if r.worker]),
        now=datetime.now(),
    )


def _run(order_id, fn, success_msg, *args):
    try:
        result = fn(*args)
        flash(success_msg(result) if callable(success_msg) else success_msg, 'success')
    except LifecycleError as e:
        db_session.rollback()
        flash(str(e), 'warning')
    return redirect(url_for('orders.detail', order_id=order_id))


@bp.route('/<int:order_id>/approve', methods=['POST'])
@login_required
def approve(order_id):
    order = get_or_404(Order, order_id)
    return _run(order_id, services.approve_order,
                lambda sent: f'Заказ #{order_id} одобрен, вакансия отправлена работникам: {sent}', order)


@bp.route('/<int:order_id>/reject', methods=['POST'])
@login_required
def reject(order_id):
    order = get_or_404(Order, order_id)
    reason = (request.form.get('reason') or '').strip() or 'Не указана'
    return _run(order_id, services.reject_order, f'Заказ #{order_id} отклонён', order, reason)


@bp.route('/<int:order_id>/prepayment', methods=['POST'])
@login_required
def prepayment(order_id):
    order = get_or_404(Order, order_id)
    return _run(order_id, services.request_prepayment,
                lambda amount: f'Запрошена предоплата {amount:.0f} ₽, работодатель уведомлён', order)


@bp.route('/<int:order_id>/start', methods=['POST'])
@login_required
def start(order_id):
    order = get_or_404(Order, order_id)
    return _run(order_id, services.start_shift, 'Смена отмечена начавшейся', order)


@bp.route('/<int:order_id>/complete', methods=['POST'])
@login_required
def complete(order_id):
    order = get_or_404(Order, order_id)
    return _run(order_id, services.complete_shift,
                lambda n: f'Смена завершена, работников: {n}. Работодателю отправлен запрос на оценку', order)


@bp.route('/<int:order_id>/close', methods=['POST'])
@login_required
def close(order_id):
    order = get_or_404(Order, order_id)
    return _run(order_id, services.close_order, 'Расчёт закрыт, комиссия учтена в выручке', order)


@bp.route('/<int:order_id>/cancel', methods=['POST'])
@login_required
def cancel(order_id):
    order = get_or_404(Order, order_id)
    reason = (request.form.get('reason') or '').strip() or 'Не указана'
    return _run(order_id, services.cancel_order, f'Заказ #{order_id} отменён', order, reason)


@bp.route('/<int:order_id>/update_status', methods=['POST'])
@login_required
def update_status(order_id):
    order = get_or_404(Order, order_id)
    new_status = request.form.get('status')
    return _run(order_id, services.set_status_manual,
                f'Статус обновлён: {ORDER_STATUS_NAMES.get(new_status, new_status)}', order, new_status)


@bp.route('/<int:order_id>/note', methods=['POST'])
@login_required
def note(order_id):
    get_or_404(Order, order_id)
    text = (request.form.get('text') or '').strip()
    if text:
        services.log_action('note', 'order', order_id, text)
        flash('Заметка добавлена', 'success')
    return redirect(url_for('orders.detail', order_id=order_id) + '#history')


@bp.route('/responses/<int:response_id>/<action>', methods=['POST'])
@login_required
def response_action(response_id, action):
    response = get_or_404(Response, response_id)
    order_id = response.order_id
    back = services.safe_next(url_for('orders.detail', order_id=order_id))
    try:
        if action == 'confirm':
            confirmed, filled = services.confirm_response(response)
            msg = f'Отклик подтверждён ({confirmed}/{response.order.workers_needed})'
            if filled:
                msg += ' — набор закрыт'
        elif action == 'reject':
            services.reject_response(response, (request.form.get('reason') or '').strip() or None)
            msg = 'Отклик отклонён'
        elif action == 'contact':
            services.contact_response(response)
            msg = 'Отмечено: администратор связался с работником'
        elif action == 'noshow':
            total = growth.mark_no_show(response, (request.form.get('reason') or '').strip() or None)
            msg = f'Отмечена неявка, у работника теперь {total} штрафных баллов'
        else:
            flash('Неизвестное действие', 'danger')
            return redirect(back)
        flash(msg, 'success')
    except LifecycleError as e:
        db_session.rollback()
        flash(str(e), 'warning')
    return redirect(back)


@bp.route('/<int:order_id>/point', methods=['POST'])
@login_required
def set_point(order_id):
    order = get_or_404(Order, order_id)
    try:
        res = growth.set_order_point(order, request.form.get('point'))
        flash('Точка на карте сохранена: отметки работников будут сверяться с ней' if res
              else 'Точка на карте удалена', 'success')
    except LifecycleError as e:
        db_session.rollback()
        flash(str(e), 'warning')
    return redirect(url_for('orders.detail', order_id=order_id) + '#checkins')
