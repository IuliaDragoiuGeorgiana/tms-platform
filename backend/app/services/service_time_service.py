from decimal import Decimal
from sqlalchemy.orm import Session

from app.models.order import Order, ServiceTimeSourceEnum
from app.models.system_config import SystemConfig


DEFAULT_CONFIG = {
    # base service times per cargo type
    "standard_pickup_service_min": 20,
    "standard_delivery_service_min": 15,

    "fragil_pickup_service_min": 35,
    "fragil_delivery_service_min": 25,

    "perisabil_pickup_service_min": 20,
    "perisabil_delivery_service_min": 20,

    "adr_pickup_service_min": 45,
    "adr_delivery_service_min": 30,

    # quantity-based adjustment
    "service_extra_minutes_per_500kg": 5,
    "service_extra_minutes_per_5m3": 5,

    # safety cap
    "service_max_minutes": 60,
}


def _get_config_int(db: Session, company_id, key: str) -> int:
    """
    Citește o valoare INT din SystemConfig.
    Dacă nu există configurare pentru companie, folosește fallback-ul din DEFAULT_CONFIG.
    """
    config = (
        db.query(SystemConfig)
        .filter(
            SystemConfig.company_id == company_id,
            SystemConfig.key == key,
        )
        .first()
    )

    if config is None:
        return DEFAULT_CONFIG[key]

    try:
        return int(config.value)
    except (TypeError, ValueError):
        return DEFAULT_CONFIG[key]


def _cargo_prefix(order: Order) -> str:
    cargo_type = order.type_marfa.value if hasattr(order.type_marfa, "value") else str(order.type_marfa)
    return cargo_type.lower()


def calculate_service_times_for_order(
    db: Session,
    order: Order,
) -> tuple[int, int]:
    """
    Calculează pickup_service_minutes și delivery_service_minutes pentru o comandă.

    Formula:
    service_time = base_time_by_type_marfa + extra_by_kg + extra_by_m3

    Valorile de bază vin din SystemConfig.
    Ajustarea se face pe baza kg și m3.
    """
    prefix = _cargo_prefix(order)

    pickup_base = _get_config_int(
        db,
        order.company_id,
        f"{prefix}_pickup_service_min",
    )
    delivery_base = _get_config_int(
        db,
        order.company_id,
        f"{prefix}_delivery_service_min",
    )

    extra_per_500kg = _get_config_int(
        db,
        order.company_id,
        "service_extra_minutes_per_500kg",
    )
    extra_per_5m3 = _get_config_int(
        db,
        order.company_id,
        "service_extra_minutes_per_5m3",
    )
    max_minutes = _get_config_int(
        db,
        order.company_id,
        "service_max_minutes",
    )

    kg = Decimal(order.kg or 0)
    m3 = Decimal(order.m3 or 0)

    extra_kg_minutes = int(kg / Decimal("500") * extra_per_500kg)
    extra_m3_minutes = int(m3 / Decimal("5") * extra_per_5m3)

    pickup_minutes = pickup_base + extra_kg_minutes + extra_m3_minutes
    delivery_minutes = delivery_base + extra_kg_minutes + extra_m3_minutes

    pickup_minutes = min(pickup_minutes, max_minutes)
    delivery_minutes = min(delivery_minutes, max_minutes)

    return pickup_minutes, delivery_minutes


def ensure_order_service_times(
    db: Session,
    order: Order,
) -> None:
    """
    Setează timpii de service automat doar dacă:
    - lipsesc valorile
    - sau sursa este AUTO

    Dacă Dispecerul a pus MANUAL, nu suprascriem.
    """
    if order.service_time_source == ServiceTimeSourceEnum.MANUAL:
        return

    pickup_minutes, delivery_minutes = calculate_service_times_for_order(db, order)

    order.pickup_service_minutes = pickup_minutes
    order.delivery_service_minutes = delivery_minutes
    order.service_time_source = ServiceTimeSourceEnum.AUTO