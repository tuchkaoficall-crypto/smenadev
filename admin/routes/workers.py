"""
Управление работниками
"""
from flask import Blueprint, render_template, request
from flask_login import login_required
import json

from admin import db_session
from database.models import Worker, User, Review

bp = Blueprint('workers', __name__, url_prefix='/workers')


@bp.route('/')
@login_required
def index():
    """Список работников"""
    page = request.args.get('page', 1, type=int)
    city = request.args.get('city', None)
    per_page = 20
    
    query = db_session.query(Worker).join(User)
    
    if city:
        query = query.filter(Worker.city == city)
    
    query = query.order_by(Worker.rating.desc())
    
    total = query.count()
    workers = query.offset((page - 1) * per_page).limit(per_page).all()
    
    total_pages = (total + per_page - 1) // per_page
    
    return render_template(
        'workers/index.html',
        workers=workers,
        page=page,
        total_pages=total_pages,
        city=city
    )


@bp.route('/<int:worker_id>')
@login_required
def detail(worker_id):
    """Детальная информация о работнике"""
    worker = db_session.query(Worker).filter(
        Worker.id == worker_id
    ).first_or_404()
    
    # Получаем отзывы
    reviews = db_session.query(Review).filter(
        Review.worker_id == worker_id
    ).order_by(Review.created_at.desc()).all()
    
    # Получаем категории
    categories = json.loads(worker.categories) if worker.categories else []
    
    # Получаем отклики
    responses = worker.responses
    
    return render_template(
        'workers/detail.html',
        worker=worker,
        reviews=reviews,
        categories=categories,
        responses=responses
    )
