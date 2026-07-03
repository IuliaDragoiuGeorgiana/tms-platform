from datetime import date
from types import SimpleNamespace

from app.services import planning_service
from tests.helpers import make_order


def test_get_order_planning_window_respects_all_date_constraints():
    flexible_order = make_order(flexibility_days=3)
    assert planning_service._get_order_planning_window(flexible_order) == (
        date(2026, 7, 7),
        date(2026, 7, 10),
    )

    constrained_order = make_order(
        flexibility_days=5,
        earliest_delivery_date=date(2026, 7, 8),
    )
    assert planning_service._get_order_planning_window(constrained_order) == (
        date(2026, 7, 8),
        date(2026, 7, 10),
    )

    fixed_order = make_order(flexibility_days=0)
    assert planning_service._get_order_planning_window(fixed_order) == (
        date(2026, 7, 10),
        date(2026, 7, 10),
    )


def test_calculate_day_num_clusters_uses_the_stricter_constraint(monkeypatch):
    orders = [make_order() for _ in range(3)]
    vehicles = [SimpleNamespace(capacity_kg=1_000, capacity_m3=10)]
    drivers = [SimpleNamespace()]

    monkeypatch.setattr(planning_service, "calculate_num_clusters", lambda **_: 2)
    monkeypatch.setattr(planning_service, "_driver_available_minutes", lambda _: 1_000)
    assert planning_service._calculate_day_num_clusters(orders, vehicles, drivers) == 2

    monkeypatch.setattr(planning_service, "calculate_num_clusters", lambda **_: 1)
    monkeypatch.setattr(planning_service, "_driver_available_minutes", lambda _: 100)
    assert planning_service._calculate_day_num_clusters(orders, vehicles, drivers) == 2


def test_repair_deferred_distribution_never_exceeds_day_capacity():
    planned_day = date(2026, 7, 10)
    placed = make_order(id="placed", flexibility_days=0)
    deferred = make_order(id="deferred", flexibility_days=0)
    distribution = {
        "days": {planned_day: [placed]},
        "deferred": [deferred],
        "used_minutes": {planned_day: 90},
        "capacity_by_day_minutes": {planned_day: 100},
    }
    result = planning_service._repair_deferred_distribution(
        distribution=distribution,
        date_start=planned_day,
        date_end=planned_day,
        estimated_minutes_by_order={"placed": 90, "deferred": 20},
    )
    assert result["days"][planned_day] == [placed]
    assert result["deferred"] == [deferred]
    assert result["used_minutes"][planned_day] == 90
