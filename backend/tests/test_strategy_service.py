from datetime import date, datetime

import pytest

from app.services.strategy_service import _urgency_score, distribute_greedy_deadline
from tests.helpers import make_order


def test_urgency_score_is_maximal_today_and_decreases_with_deadline():
    reference_date = date(2026, 7, 1)
    critical_today = make_order(priority="CRITIC", delivery_deadline=reference_date)
    critical_tomorrow = make_order(
        priority="CRITIC",
        delivery_deadline=date(2026, 7, 2),
    )
    critical_later = make_order(
        priority="CRITIC",
        delivery_deadline=date(2026, 7, 6),
    )

    assert _urgency_score(critical_today, reference_date) == pytest.approx(1.0)
    assert _urgency_score(critical_today, reference_date) > _urgency_score(
        critical_tomorrow,
        reference_date,
    )
    assert _urgency_score(critical_tomorrow, reference_date) > _urgency_score(
        critical_later,
        reference_date,
    )


def test_longer_horizon_adds_capacity_instead_of_forcing_orders_into_one_day():
    start = date(2026, 7, 1)
    orders = [
        make_order(
            id=f"order-{index}",
            was_postponed=False,
            created_at=datetime(2026, 6, 1, 8, index),
            delivery_deadline=date(2026, 7, 3),
            earliest_delivery_date=start,
            flexibility_days=2,
        )
        for index in range(3)
    ]
    estimates = {str(order.id): 60 for order in orders}
    one_day = distribute_greedy_deadline(
        orders, [start], {start: 100}, estimates
    )
    three_days = distribute_greedy_deadline(
        orders,
        [start, date(2026, 7, 2), date(2026, 7, 3)],
        {start: 100, date(2026, 7, 2): 100, date(2026, 7, 3): 100},
        estimates,
    )
    assert len(one_day["days"][start]) == 1
    assert len(one_day["deferred"]) == 2
    assert sum(len(items) for items in three_days["days"].values()) == 3
    assert three_days["deferred"] == []
