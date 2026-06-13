from app.models.order import Order


def _enum_value(value) -> str:
    """Returnează valoarea string pentru Enum sau string simplu."""
    return value.value if hasattr(value, "value") else str(value)


def check_order_operational_warnings(order: Order) -> list[str]:
    """
    Verificări operaționale simple pentru Order Pool / Planning.

    Aceste warnings NU blochează automat comanda.
    Ele ajută Dispecerul să vadă riscurile înainte de generarea planului.
    """
    warnings: list[str] = []

    cargo_type = _enum_value(order.type_marfa)
    priority = _enum_value(order.priority)

    kg = float(order.kg or 0)
    m3 = float(order.m3 or 0)

    pickup_service = int(order.pickup_service_minutes or 0)
    delivery_service = int(order.delivery_service_minutes or 0)
    total_service = pickup_service + delivery_service

    # Prioritate
    if priority == "URGENT":
        warnings.append(
            "Comandă URGENTĂ: trebuie prioritizată în planificare."
        )

    if priority == "CRITIC":
        warnings.append(
            "Comandă CRITICĂ: necesită atenție maximă și risc crescut dacă este întârziată."
        )

    # Tip marfă
    if cargo_type == "ADR":
        warnings.append(
            "Marfă ADR: necesită verificări speciale de siguranță și compatibilitate."
        )

    if cargo_type == "FRAGIL" and kg >= 500:
        warnings.append(
            "Marfă FRAGILĂ cu greutate mare: poate necesita manipulare suplimentară."
        )

    if cargo_type == "PERISABIL":
        warnings.append(
            "Marfă PERISABILĂ: timpul de livrare și așteptare trebuie monitorizate atent."
        )

    # Service time mare
    if total_service >= 90:
        warnings.append(
            "Timp total de service ridicat: poate afecta durata cursei și ETA-urile."
        )

    return warnings