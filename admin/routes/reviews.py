"""
Модерация отзывов: скрытие/восстановление с пересчётом рейтинга работника
"""
from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required

from admin import db_session, get_or_404
from admin import services
from database.models import Review

bp = Blueprint('reviews', __name__, url_prefix='/reviews')


@bp.route('/')
@login_required
def index():
    q = db_session.query(Review)
    flt = request.args.get('filter')
    if flt == 'hidden':
        q = q.filter(Review.is_hidden.is_(True))
    elif flt == 'low':
        q = q.filter(Review.rating <= 2)
    reviews = q.order_by(Review.created_at.desc()).limit(200).all()
    return render_template('reviews/index.html', reviews=reviews, flt=flt)


@bp.route('/<int:review_id>/hide', methods=['POST'])
@login_required
def hide(review_id):
    review = get_or_404(Review, review_id)
    review.is_hidden = True
    review.hidden_reason = (request.form.get('reason') or '').strip() or None
    services.recalc_worker_rating(review.worker)
    services.log_action('review_hide', 'worker', review.worker_id,
                        f"Отзыв #{review.id} ({review.rating}★)" + (f": {review.hidden_reason}" if review.hidden_reason else ""),
                        commit=False)
    db_session.commit()
    flash('Отзыв скрыт, рейтинг работника пересчитан', 'success')
    return redirect(services.safe_next(url_for('reviews.index')))


@bp.route('/<int:review_id>/unhide', methods=['POST'])
@login_required
def unhide(review_id):
    review = get_or_404(Review, review_id)
    review.is_hidden = False
    review.hidden_reason = None
    services.recalc_worker_rating(review.worker)
    services.log_action('review_unhide', 'worker', review.worker_id, f"Отзыв #{review.id}", commit=False)
    db_session.commit()
    flash('Отзыв восстановлен, рейтинг пересчитан', 'success')
    return redirect(services.safe_next(url_for('reviews.index')))
