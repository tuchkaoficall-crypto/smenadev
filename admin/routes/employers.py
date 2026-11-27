"""
Управление работодателями: поиск, CSV, статистика, модерация, блокировка
"""
from datetime import datetime

from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required
from sqlalchemy import or_

from admin import db_session, get_or_404
from admin import services, telegram
from database.models import Employer, User
from config import EmployerStatus, EMPLOYER_STATUS_NAMES, ORDER_STATUS_NAMES, OrderStatus

bp = Blueprint('employers', __name__, url_prefix='/employers')


def _filtered_query():
    query = db_session.query(Employer).join(User, Employer.user_id == User.id)
    status = request.args.get('status')
    if status:
        query = query.filter(Employer.status == status)
    q = (request.args.get('q') or '').strip()
    if q:
        like = f"%{q}%"
        conds = [Employer.company_name.ilike(like), Employer.contact_person.ilike(like),
                 Employer.contact_phone.ilike(like), Employer.inn.ilike(like),
                 Employer.contact_email.ilike(like), User.username.ilike(like)]
        if q.isdigit():
            conds.append(Employer.user_id == int(q))
        query = query.filter(or_(*conds))
    return query.order_by(Employer.created_at.desc())


def _stats(employer):
    orders = employer.orders
    done = [o for o in orders if o.status == OrderStatus.PAYMENT_COMPLETED]
    return {
        "orders": len(orders),
        "active": sum(1 for o in orders if o.status in services.ACTIVE_STATUSES),
        "done": len(done),
        "cancelled": sum(1 for o in orders if o.status == OrderStatus.CANCELLED),
        "gmv": sum(services.order_gmv(o) for o in orders if o.status != OrderStatus.CANCELLED),
        "commission": sum(o.commission or 0 for o in done),
        "reviews": len(employer.reviews),
    }


@bp.route('/')
@login_required
def index():
    page = request.args.get('page', 1, type=int)
    per_page = 25
    query = _filtered_query()
    total = query.count()
    employers = query.offset((page - 1) * per_page).limit(per_page).all()
    counts = {s: db_session.query(Employer).filter(Employer.status == s).count() for s in EMPLOYER_STATUS_NAMES}
    return render_template(
        'employers/index.html',
        employers=employers, stats={e.id: _stats(e) for e in employers},
        page=page, total=total, total_pages=(total + per_page - 1) // per_page,
        status=request.args.get('status'), status_names=EMPLOYER_STATUS_NAMES, counts=counts,
        args={k: v for k, v in request.args.items() if k != 'page'},
    )


@bp.route('/export.csv')
@login_required
def export_csv():
    rows = []
    for e in _filtered_query().all():
        s = _stats(e)
        rows.append([e.id, e.company_name, e.inn or '', e.contact_person, e.contact_phone,
                     e.contact_email or '', f"@{e.user.username}" if e.user and e.user.username else '',
                     e.user_id, EMPLOYER_STATUS_NAMES.get(e.status, e.status), s['orders'], s['done'],
                     round(s['gmv'], 2), round(s['commission'], 2), services.fmt_dt(e.created_at)])
    return services.csv_response(
        f"employers_{datetime.now():%Y%m%d_%H%M}.csv",
        ["ID", "Компания", "ИНН", "Контакт", "Телефон", "Email", "Telegram", "Telegram ID", "Статус",
         "Заказов", "Закрыто", "ФОТ", "Комиссия", "Регистрация"],
        rows,
    )


@bp.route('/<int:employer_id>')
@login_required
def detail(employer_id):
    employer = get_or_404(Employer, employer_id)
    orders = sorted(employer.orders, key=lambda o: o.created_at or datetime.min, reverse=True)
    return render_template(
        'employers/detail.html',
        employer=employer, orders=orders, stats=_stats(employer),
        status_names=EMPLOYER_STATUS_NAMES, order_status_names=ORDER_STATUS_NAMES,
        history=services.entity_history('employer', employer.id),
    )


@bp.route('/<int:employer_id>/approve', methods=['POST'])
@login_required
def approve(employer_id):
    employer = get_or_404(Employer, employer_id)
    employer.status = EmployerStatus.APPROVED
    employer.approved_at = datetime.utcnow()
    if employer.user:
        employer.user.is_blocked = False
    services.log_action('employer_approve', 'employer', employer.id, employer.company_name, commit=False)
    db_session.commit()
    telegram.send_message(
        employer.user_id,
        "✅ Поздравляем! Ваша анкета одобрена.\n\nТеперь вы можете создавать заявки на подбор работников."
    )
    flash(f'Работодатель {employer.company_name} одобрен', 'success')
    return redirect(services.safe_next(url_for('employers.detail', employer_id=employer_id)))


@bp.route('/<int:employer_id>/reject', methods=['POST'])
@login_required
def reject(employer_id):
    employer = get_or_404(Employer, employer_id)
    reason = (request.form.get('reason') or '').strip() or 'Не указана'
    employer.status = EmployerStatus.REJECTED
    employer.rejection_reason = reason
    services.log_action('employer_reject', 'employer', employer.id, reason, commit=False)
    db_session.commit()
    telegram.send_message(
        employer.user_id,
        f"❌ К сожалению, ваша анкета отклонена.\n\nПричина: {reason}\n\n"
        "Вы можете заполнить анкету заново: нажмите /start."
    )
    flash(f'Работодатель {employer.company_name} отклонён', 'warning')
    return redirect(services.safe_next(url_for('employers.detail', employer_id=employer_id)))


@bp.route('/<int:employer_id>/block', methods=['POST'])
@login_required
def block(employer_id):
    employer = get_or_404(Employer, employer_id)
    reason = (request.form.get('reason') or '').strip()
    employer.status = EmployerStatus.BLOCKED
    employer.user.is_blocked = True
    services.log_action('employer_block', 'employer', employer.id, reason or employer.company_name, commit=False)
    db_session.commit()
    flash(f'Работодатель {employer.company_name} заблокирован', 'danger')
    return redirect(url_for('employers.detail', employer_id=employer_id))


@bp.route('/<int:employer_id>/unblock', methods=['POST'])
@login_required
def unblock(employer_id):
    employer = get_or_404(Employer, employer_id)
    employer.status = EmployerStatus.APPROVED
    employer.user.is_blocked = False
    services.log_action('employer_unblock', 'employer', employer.id, employer.company_name, commit=False)
    db_session.commit()
    flash(f'Работодатель {employer.company_name} разблокирован', 'success')
    return redirect(url_for('employers.detail', employer_id=employer_id))


@bp.route('/<int:employer_id>/note', methods=['POST'])
@login_required
def note(employer_id):
    get_or_404(Employer, employer_id)
    text = (request.form.get('text') or '').strip()
    if text:
        services.log_action('note', 'employer', employer_id, text)
        flash('Заметка добавлена', 'success')
    return redirect(url_for('employers.detail', employer_id=employer_id))
