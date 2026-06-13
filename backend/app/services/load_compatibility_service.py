from app.models.order import Order
from app.models.vehicle import Vehicle


def _enum_value(value) -> str:
    """Returnează valoarea string pentru Enum sau string simplu."""
    return value.value if hasattr(value, "value") else str(value)


def check_load_compatibility_warnings(
    cluster_orders: list[Order],
    vehicle: Vehicle,
    total_minutes: int | None = None,
    peak_kg: float | None = None,
    peak_m3: float | None = None,
) -> list[dict]:
    """
    Verifică riscuri de compatibilitate a încărcăturii pentru o cursă.

    Aceste verificări NU blochează planificarea.
    Ele generează warnings pentru Dispecer, ca suport decizional.
    """
    warnings: list[dict] = []

    if not cluster_orders or not vehicle:
        return warnings

    cargo_types = {
        _enum_value(order.type_marfa)
        for order in cluster_orders
    }

    total_kg = sum(float(order.kg or 0) for order in cluster_orders)
    total_m3 = sum(float(order.m3 or 0) for order in cluster_orders)

    vehicle_capacity_kg = float(vehicle.capacity_kg or 0)
    vehicle_capacity_m3 = float(vehicle.capacity_m3 or 0)

    effective_kg = peak_kg if peak_kg is not None else total_kg
    effective_m3 = peak_m3 if peak_m3 is not None else total_m3

    kg_utilization = (
        effective_kg / vehicle_capacity_kg
        if vehicle_capacity_kg > 0
        else 0
    )

    m3_utilization = (
        effective_m3 / vehicle_capacity_m3
        if vehicle_capacity_m3 > 0
        else 0
    )

    # 1. ADR + alt tip de marfă
    if "ADR" in cargo_types and len(cargo_types) > 1:
        warnings.append({
            "type": "LOAD_COMPATIBILITY_WARNING",
            "severity": "WARNING",
            "message": (
                "Cursa conține marfă ADR împreună cu alte tipuri de marfă. "
                "Este recomandată verificarea manuală a compatibilității."
            ),
        })

    # 2. PERISABIL + durată mare
    if "PERISABIL" in cargo_types and total_minutes is not None and total_minutes >= 240:
        warnings.append({
            "type": "LOAD_COMPATIBILITY_WARNING",
            "severity": "WARNING",
            "message": (
                "Cursa conține marfă PERISABILĂ și are durată planificată mare. "
                "Verifică timpul de transport și eventualele perioade de așteptare."
            ),
        })

    # 3. FRAGIL + greutate totală mare
    if "FRAGIL" in cargo_types and total_kg >= 1000:
        warnings.append({
            "type": "LOAD_COMPATIBILITY_WARNING",
            "severity": "WARNING",
            "message": (
                "Cursa conține marfă FRAGILĂ și greutate totală ridicată. "
                "Este recomandată atenție la manipulare și poziționare în vehicul."
            ),
        })

    # 4. Utilizare vehicul peste 80% kg
    if kg_utilization >= 0.80:
        warnings.append({
            "type": "LOAD_COMPATIBILITY_WARNING",
            "severity": "WARNING",
            "message": (
                f"Vehiculul atinge un vârf de încărcare de aproximativ {kg_utilization * 100:.0f}% "
                    "din capacitatea de greutate."
            ),
        })

    # 5. Utilizare vehicul peste 80% m3
    if m3_utilization >= 0.80:
        warnings.append({
            "type": "LOAD_COMPATIBILITY_WARNING",
            "severity": "WARNING",
            "message": (
                f"Vehiculul atinge un vârf de încărcare de aproximativ {m3_utilization * 100:.0f}% "
                    "din capacitatea de volum."
            ),
        })

    # 6. Comandă individuală aproape de capacitatea vehiculului
    for order in cluster_orders:
        order_kg = float(order.kg or 0)
        order_m3 = float(order.m3 or 0)

        order_ref = getattr(order, "order_ref", "N/A")

        if vehicle_capacity_kg > 0 and order_kg / vehicle_capacity_kg >= 0.80:
            warnings.append({
                "type": "LOAD_COMPATIBILITY_WARNING",
                "severity": "WARNING",
                "order_id": str(order.id),
                "order_ref": order_ref,
                "message": (
                    f"Comanda {order_ref} folosește peste 80% din capacitatea "
                    "de greutate a vehiculului."
                ),
            })

        if vehicle_capacity_m3 > 0 and order_m3 / vehicle_capacity_m3 >= 0.80:
            warnings.append({
                "type": "LOAD_COMPATIBILITY_WARNING",
                "severity": "WARNING",
                "order_id": str(order.id),
                "order_ref": order_ref,
                "message": (
                    f"Comanda {order_ref} folosește peste 80% din capacitatea "
                    "de volum a vehiculului."
                ),
            })

    return warnings