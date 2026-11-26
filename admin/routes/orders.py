"""
Управление заказами
"""
from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required
from datetime import datetime

from admin import db_session
from database.models import Order, Response
from config import OrderStatus, ORDER_STATUS_NAMES, RESPONSE_STATUS_NAMES

bp = Blueprint('orders', __name__, url_prefix='/orders')


@bp.route('/')
@login_required
def index():
    """Список заказов"""
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', None)
    per_page = 20
    
    query = db_session.query(Order)
    
    if status:
        query = query.filter(Order.status == status)
    
    query = query.order_by(Order.created_at.desc())
    
    total = query.count()
    orders = query.offset((page - 1) * per_page).limit(per_page).all()
    
    total_pages = (total + per_page - 1) // per_page
    
    return render_template(
        'orders/index.html',
        orders=orders,
        page=page,
        total_pages=total_pages,
        status=status,
        status_names=ORDER_STATUS_NAMES
    )


@bp.route('/<int:order_id>')
@login_required
def detail(order_id):
    """Детальная информация о заказе"""
    order = db_session.query(Order).filter(
        Order.id == order_id
    ).first_or_404()
    
    # Получаем отклики
    responses = db_session.query(Response).filter(
        Response.order_id == order_id
    ).order_by(Response.created_at.desc()).all()
    
    return render_template(
        'orders/detail.html',
        order=order,
        responses=responses,
        status_names=ORDER_STATUS_NAMES,
        response_status_names=RESPONSE_STATUS_NAMES
    )


@bp.route('/<int:order_id>/approve', methods=['POST'])
@login_required
def approve(order_id):
    """Одобрить заказ"""
    order = db_session.query(Order).filter(
        Order.id == order_id
    ).first_or_404()
    
    order.status = OrderStatus.SEARCH_WORKERS
    order.moderated_at = datetime.utcnow()
    
    db_session.commit()
    
    flash(f'Заказ #{order_id} одобрен', 'success')
    return redirect(url_for('orders.detail', order_id=order_id))


@bp.route('/<int:order_id>/reject', methods=['POST'])
@login_required
def reject(order_id):
    """Отклонить заказ"""
    order = db_session.query(Order).filter(
        Order.id == order_id
    ).first_or_404()
    
    reason = request.form.get('reason', 'Не указана')
    
    order.status = OrderStatus.CANCELLED
    order.rejection_reason = reason
    
    db_session.commit()
    
    flash(f'Заказ #{order_id} отклонён', 'warning')
    return redirect(url_for('orders.detail', order_id=order_id))


@bp.route('/<int:order_id>/update_status', methods=['POST'])
@login_required
def update_status(order_id):
    """Обновить статус заказа"""
    order = db_session.query(Order).filter(
        Order.id == order_id
    ).first_or_404()
    
    new_status = request.form.get('status')
    
    if new_status in ORDER_STATUS_NAMES:
        order.status = new_status
        
        # Обновляем даты
        if new_status == OrderStatus.SHIFT_STARTED:
            order.started_at = datetime.utcnow()
        elif new_status == OrderStatus.SHIFT_COMPLETED:
            order.completed_at = datetime.utcnow()
        elif new_status == OrderStatus.PAYMENT_COMPLETED:
            order.closed_at = datetime.utcnow()
        
        db_session.commit()
        flash(f'Статус заказа обновлён на: {ORDER_STATUS_NAMES[new_status]}', 'success')
    else:
        flash('Неверный статус', 'danger')
    
    return redirect(url_for('orders.detail', order_id=order_id))
