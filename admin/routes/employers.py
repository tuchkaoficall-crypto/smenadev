"""
Управление работодателями
"""
from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required
from datetime import datetime

from admin import db_session
from database.models import Employer, User
from config import EmployerStatus, EMPLOYER_STATUS_NAMES

bp = Blueprint('employers', __name__, url_prefix='/employers')


@bp.route('/')
@login_required
def index():
    """Список работодателей"""
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', None)
    per_page = 20
    
    query = db_session.query(Employer).join(User)
    
    if status:
        query = query.filter(Employer.status == status)
    
    query = query.order_by(Employer.created_at.desc())
    
    total = query.count()
    employers = query.offset((page - 1) * per_page).limit(per_page).all()
    
    total_pages = (total + per_page - 1) // per_page
    
    return render_template(
        'employers/index.html',
        employers=employers,
        page=page,
        total_pages=total_pages,
        status=status,
        status_names=EMPLOYER_STATUS_NAMES
    )


@bp.route('/<int:employer_id>')
@login_required
def detail(employer_id):
    """Детальная информация о работодателе"""
    employer = db_session.query(Employer).filter(
        Employer.id == employer_id
    ).first_or_404()
    
    # Получаем заказы работодателя
    orders = employer.orders
    
    return render_template(
        'employers/detail.html',
        employer=employer,
        orders=orders,
        status_names=EMPLOYER_STATUS_NAMES
    )


@bp.route('/<int:employer_id>/approve', methods=['POST'])
@login_required
def approve(employer_id):
    """Одобрить работодателя"""
    employer = db_session.query(Employer).filter(
        Employer.id == employer_id
    ).first_or_404()
    
    employer.status = EmployerStatus.APPROVED
    employer.approved_at = datetime.utcnow()
    
    db_session.commit()
    
    flash(f'Работодатель {employer.company_name} одобрен', 'success')
    return redirect(url_for('employers.detail', employer_id=employer_id))


@bp.route('/<int:employer_id>/reject', methods=['POST'])
@login_required
def reject(employer_id):
    """Отклонить работодателя"""
    employer = db_session.query(Employer).filter(
        Employer.id == employer_id
    ).first_or_404()
    
    reason = request.form.get('reason', 'Не указана')
    
    employer.status = EmployerStatus.REJECTED
    employer.rejection_reason = reason
    
    db_session.commit()
    
    flash(f'Работодатель {employer.company_name} отклонён', 'warning')
    return redirect(url_for('employers.detail', employer_id=employer_id))


@bp.route('/<int:employer_id>/block', methods=['POST'])
@login_required
def block(employer_id):
    """Заблокировать работодателя"""
    employer = db_session.query(Employer).filter(
        Employer.id == employer_id
    ).first_or_404()
    
    employer.status = EmployerStatus.BLOCKED
    employer.user.is_blocked = True
    
    db_session.commit()
    
    flash(f'Работодатель {employer.company_name} заблокирован', 'danger')
    return redirect(url_for('employers.detail', employer_id=employer_id))
