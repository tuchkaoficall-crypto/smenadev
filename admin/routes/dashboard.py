"""
Дашборд админ-панели
"""
from flask import Blueprint, render_template
from flask_login import login_required
from sqlalchemy import func

from admin import db_session
from database.models import User, Employer, Worker, Order, Response, Review
from config import EmployerStatus, OrderStatus, ResponseStatus

bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')


@bp.route('/')
@login_required
def index():
    """Главный дашборд"""
    # Статистика пользователей
    total_users = db_session.query(User).count()
    total_employers = db_session.query(Employer).count()
    total_workers = db_session.query(Worker).count()
    
    # Статистика работодателей
    pending_employers = db_session.query(Employer).filter(
        Employer.status == EmployerStatus.PENDING
    ).count()
    approved_employers = db_session.query(Employer).filter(
        Employer.status == EmployerStatus.APPROVED
    ).count()
    
    # Статистика заказов
    total_orders = db_session.query(Order).count()
    pending_orders = db_session.query(Order).filter(
        Order.status == OrderStatus.MODERATION
    ).count()
    active_orders = db_session.query(Order).filter(
        Order.status.in_([
            OrderStatus.SEARCH_WORKERS,
            OrderStatus.CONFIRM_WORKERS,
            OrderStatus.SHIFT_STARTED
        ])
    ).count()
    completed_orders = db_session.query(Order).filter(
        Order.status == OrderStatus.PAYMENT_COMPLETED
    ).count()
    
    # Статистика откликов
    total_responses = db_session.query(Response).count()
    pending_responses = db_session.query(Response).filter(
        Response.status == ResponseStatus.PENDING
    ).count()
    
    # Статистика отзывов
    total_reviews = db_session.query(Review).count()
    
    # Финансовая статистика
    total_commission = db_session.query(
        func.sum(Order.commission)
    ).filter(
        Order.status == OrderStatus.PAYMENT_COMPLETED
    ).scalar() or 0
    
    # Последние действия
    recent_orders = db_session.query(Order).order_by(
        Order.created_at.desc()
    ).limit(5).all()
    
    recent_responses = db_session.query(Response).order_by(
        Response.created_at.desc()
    ).limit(5).all()
    
    return render_template(
        'dashboard/index.html',
        stats={
            'users': {
                'total': total_users,
                'employers': total_employers,
                'workers': total_workers
            },
            'employers': {
                'pending': pending_employers,
                'approved': approved_employers
            },
            'orders': {
                'total': total_orders,
                'pending': pending_orders,
                'active': active_orders,
                'completed': completed_orders
            },
            'responses': {
                'total': total_responses,
                'pending': pending_responses
            },
            'reviews': total_reviews,
            'commission': total_commission
        },
        recent_orders=recent_orders,
        recent_responses=recent_responses
    )
