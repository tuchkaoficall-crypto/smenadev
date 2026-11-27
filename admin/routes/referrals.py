"""
Реферальная программа: кто кого пригласил, начисленные и выплаченные бонусы
"""
from datetime import datetime

from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required

from admin import db_session, get_or_404
from admin import growth, services
from admin.services import LifecycleError
from database.models import Referral
from config import REFERRAL_STATUS_NAMES, REFERRAL_BONUS

bp = Blueprint('referrals', __name__, url_prefix='/referrals')


@bp.route('/')
@login_required
def index():
    status = request.args.get('status') or None
    refs, users, workers, employers = growth.referral_rows(status)
    return render_template('referrals/index.html', refs=refs, users=users, workers=workers,
                           employers=employers, stats=growth.referral_stats(), status=status,
                           statuses=REFERRAL_STATUS_NAMES, bonus=REFERRAL_BONUS)


@bp.route('/export.csv')
@login_required
def export_csv():
    refs, users, _, _ = growth.referral_rows(request.args.get('status') or None)
    name = lambda uid: users[uid].full_name if uid in users else str(uid)  # noqa: E731
    rows = [[r.id, r.referrer_id, name(r.referrer_id), r.referred_id, name(r.referred_id), r.role or '',
             REFERRAL_STATUS_NAMES.get(r.status, r.status), r.bonus_amount or 0,
             services.fmt_dt(r.created_at), services.fmt_dt(r.qualified_at), services.fmt_dt(r.paid_at)]
            for r in refs]
    return services.csv_response(
        f"referrals_{datetime.now():%Y%m%d_%H%M}.csv",
        ["ID", "Пригласил (ID)", "Пригласил", "Приглашён (ID)", "Приглашён", "Роль", "Статус", "Бонус",
         "Дата", "Начислен", "Выплачен"], rows)


@bp.route('/<int:ref_id>/<status>', methods=['POST'])
@login_required
def set_status(ref_id, status):
    ref = get_or_404(Referral, ref_id)
    try:
        growth.referral_set_status(ref, status, (request.form.get('comment') or '').strip() or None)
        flash(f'Статус: {REFERRAL_STATUS_NAMES.get(status, status)}', 'success')
    except LifecycleError as e:
        db_session.rollback()
        flash(str(e), 'warning')
    return redirect(services.safe_next(url_for('referrals.index')))
