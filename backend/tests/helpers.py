from datetime import date
from types import SimpleNamespace


def make_order(**overrides):
    values = {
        "delivery_deadline": date(2026, 7, 10),
        "earliest_delivery_date": None,
        "flexibility_days": 0,
        "priority": "NORMAL",
        "type_marfa": "STANDARD",
        "kg": 100,
        "m3": 1,
        "pickup_service_minutes": 10,
        "delivery_service_minutes": 5,
    }
    values.update(overrides)
    return SimpleNamespace(**values)
