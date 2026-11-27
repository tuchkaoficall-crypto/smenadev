"""
Дашборд: KPI, графики выручки/комиссии, воронка заказов, требующие внимания задачи
"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request
from flask_login import login_required

from admin import db_session
from admin import services
from database.models import User, Employer, Worker, Order, Response, Review, Payment
from config import EmployerStatus, OrderStatus, ResponseStatus, ORDER_STATUS_NAMES

bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')

PERIODS = {7: "7 дней", 30: "30 дней", 90: "90 дней", 365: "Год"}


@bp.route('/')
@login_required
def index():
    days = request.args.get('days', 30, type=int)
    if days not in PERIODS:
        days = 30
    now = datetime.utcnow()
    since = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    prev_since = since - timedelta(days=days)

    orders = db_session.query(Order).all()
    period_orders = [o for o in orders if o.created_at and o.created_at >= since]
    prev_orders = [o for o in orders if o.created_at and prev_since <= o.created_at < since]

    def earned(items):
        return sum(o.commission or 0 for o in items if o.status == OrderStatus.PAYMENT_COMPLETED)

    def gmv(items):
        return sum(services.order_gmv(o) for o in items if o.status != OrderStatus.CANCELLED)

    def delta(cur, prev):
        if not prev:
            return None
        return round((cur - prev) / prev * 100)

    closed_in_period = [o for o in orders if o.closed_at and o.closed_at >= since]
    closed_prev = [o for o in orders if o.closed_at and prev_since <= o.closed_at < since]

    # Заполняемость: подтверждено / требовалось по заказам, прошедшим модерацию
    staffed = [o for o in period_orders if o.status not in services.MODERATION_STATUSES
               and o.status != OrderStatus.CANCELLED]
    need = sum(o.workers_needed or 0 for o in staffed)
    got = sum(
        min(o.workers_needed or 0,
            sum(1 for r in o.responses if r.status in (ResponseStatus.CONFIRMED, ResponseStatus.COMPLETED)))
        for o in staffed
    )
    fill_rate = round(got / need * 100) if need else None

    cancelled = sum(1 for o in period_orders if o.status == OrderStatus.CANCELLED)

    received = db_session.query(Payment).filter(Payment.status == "completed").all()
    received_period = sum(p.amount for p in received if p.paid_at and p.paid_at >= since)
    pending_payments = db_session.query(Payment).filter(Payment.status == "pending").all()

    pipeline_commission = sum(o.commission or 0 for o in orders if o.status in services.ACTIVE_STATUSES)

    kpi = {
        "gmv": gmv(period_orders), "gmv_delta": delta(gmv(period_orders), gmv(prev_orders)),
        "earned": sum(o.commission or 0 for o in closed_in_period),
        "earned_delta": delta(sum(o.commission or 0 for o in closed_in_period),
                              sum(o.commission or 0 for o in closed_prev)),
        "orders": len(period_orders), "orders_delta": delta(len(period_orders), len(prev_orders)),
        "fill_rate": fill_rate,
        "cancel_rate": round(cancelled / len(period_orders) * 100) if period_orders else None,
        "pipeline": pipeline_commission,
        "received": received_period,
        "pending_payments": sum(p.amount for p in pending_payments),
        "pending_payments_count": len(pending_payments),
        "avg_check": (gmv(period_orders) / len([o for o in period_orders if o.status != OrderStatus.CANCELLED])
                      if [o for o in period_orders if o.status != OrderStatus.CANCELLED] else 0),
        "earned_total": earned(orders),
    }

    # Серии по дням
    labels, by_day_orders, by_day_gmv, by_day_comm = [], defaultdict(int), defaultdict(float), defaultdict(float)
    for o in period_orders:
        d = o.created_at.date()
        by_day_orders[d] += 1
        if o.status != OrderStatus.CANCELLED:
            by_day_gmv[d] += services.order_gmv(o)
    for o in closed_in_period:
        by_day_comm[o.closed_at.date()] += o.commission or 0
    series = {"labels": [], "orders": [], "gmv": [], "commission": []}
    for i in range(days):
        d = (since + timedelta(days=i)).date()
        series["labels"].append(d.strftime("%d.%m"))
        series["orders"].append(by_day_orders[d])
        series["gmv"].append(round(by_day_gmv[d]))
        series["commission"].append(round(by_day_comm[d]))

    # Воронка по статусам (все заказы)
    status_counts = Counter(o.status for o in orders)
    funnel = [
        {"status": s, "name": ORDER_STATUS_NAMES[s], "count": status_counts.get(s, 0),
         "color": services.ORDER_STATUS_COLORS.get(s, "secondary")}
        for s in ORDER_STATUS_NAMES
    ]

    # Категории и работодатели за период
    cat_counter = Counter(o.category for o in period_orders)
    categories = cat_counter.most_common(8)

    emp_stats = defaultdict(lambda: {"orders": 0, "gmv": 0.0, "commission": 0.0, "employer": None})
    for o in period_orders:
        e = emp_stats[o.employer_id]
        e["employer"] = o.employer
        e["orders"] += 1
        if o.status != OrderStatus.CANCELLED:
            e["gmv"] += services.order_gmv(o)
            e["commission"] += o.commission or 0
    top_employers = sorted(emp_stats.values(), key=lambda x: x["gmv"], reverse=True)[:5]

    top_workers = db_session.query(Worker).filter(Worker.completed_shifts > 0).order_by(
        Worker.completed_shifts.desc(), Worker.rating.desc()).limit(5).all()

    # Требует внимания
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today_start + timedelta(days=1)
    attention = {
        "employers_pending": db_session.query(Employer).filter(Employer.status == EmployerStatus.PENDING).count(),
        "orders_moderation": status_counts.get(OrderStatus.CREATED, 0) + status_counts.get(OrderStatus.MODERATION, 0),
        "responses_pending": db_session.query(Response).filter(Response.status == ResponseStatus.PENDING).count(),
        "shifts_today": [o for o in orders if o.shift_date and today_start <= o.shift_date < tomorrow
                         and o.status not in services.FINAL_STATUSES],
        # Смена уже должна была пройти, а заказ всё ещё не завершён
        "overdue": [o for o in orders if o.shift_date and o.shift_duration
                    and o.shift_date + timedelta(hours=o.shift_duration) < now
                    and o.status in (OrderStatus.SEARCH_WORKERS, OrderStatus.CONFIRM_WORKERS,
                                     OrderStatus.PREPAYMENT, OrderStatus.SHIFT_STARTED)],
        "understaffed": [o for o in orders if o.status == OrderStatus.SEARCH_WORKERS and o.shift_date
                         and now <= o.shift_date < now + timedelta(hours=48)
                         and services.confirmed_count(o) < (o.workers_needed or 0)],
    }

    users = {
        "total": db_session.query(User).count(),
        "workers": db_session.query(Worker).count(),
        "employers": db_session.query(Employer).count(),
        "new": db_session.query(User).filter(User.created_at >= since).count(),
        "blocked": db_session.query(User).filter(User.is_blocked.is_(True)).count(),
        "reviews": db_session.query(Review).count(),
    }

    from database.models import AdminAction
    recent_actions = db_session.query(AdminAction).order_by(AdminAction.created_at.desc()).limit(8).all()
    recent_orders = sorted(orders, key=lambda o: o.created_at or datetime.min, reverse=True)[:6]

    return render_template(
        'dashboard/index.html',
        days=days, periods=PERIODS, kpi=kpi, series=series, funnel=funnel,
        categories=categories, top_employers=top_employers, top_workers=top_workers,
        attention=attention, users=users, recent_actions=recent_actions, recent_orders=recent_orders,
    )
