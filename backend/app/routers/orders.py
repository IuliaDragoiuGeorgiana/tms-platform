from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
import uuid
import secrets
from datetime import date

from app.database import get_db
from app.models.order import Order, MarfaTypeEnum, PriorityEnum, OrderStatusEnum, OrderSourceEnum
from app.models.user import User
from app.schemas.order import CreateOrderRequest, OrderResponse
from app.dependencies import require_roles, get_current_user

router = APIRouter(prefix="/orders", tags=["Orders"])


def generate_order_ref() -> str:
    return f"TMS-{secrets.token_hex(4).upper()}"


def generate_tracking_token() -> str:
    return secrets.token_urlsafe(16)


@router.post("/", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(
    data: CreateOrderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("CLIENT", "DISPECER", "MANAGER")),
):
    """
    Plasează o comandă de transport.
    Clientul specifică: de unde preia marfa (pickup) și unde o livrează (delivery).
    """
    current_role = current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role)

    if current_role == "CLIENT":
        if not current_user.company_id:
            raise HTTPException(status_code=400, detail="Nu ești asociat niciunei companii")
        client_id = current_user.id
        company_id = current_user.company_id
    else:
        client_id = current_user.id
        company_id = current_user.company_id

    # Calculează flexibility_days
    flexibility_days = 0
    if data.earliest_delivery_date:
        delta = data.delivery_deadline - data.earliest_delivery_date
        flexibility_days = max(0, delta.days)

    # Generează referințe unice
    order_ref = generate_order_ref()
    while db.query(Order).filter(Order.order_ref == order_ref).first():
        order_ref = generate_order_ref()

    tracking_token = generate_tracking_token()

    new_order = Order(
        company_id=company_id,
        order_ref=order_ref,
        client_id=client_id,

        # Pickup
        address_pickup=data.address_pickup,
        pickup_time_window_start=data.pickup_time_window_start,
        pickup_time_window_end=data.pickup_time_window_end,

        # Delivery
        address_delivery=data.address_delivery,
        delivery_time_window_start=data.delivery_time_window_start,
        delivery_time_window_end=data.delivery_time_window_end,

        # Marfă
        kg=data.kg,
        m3=data.m3,
        type_marfa=MarfaTypeEnum(data.type_marfa),
        priority=PriorityEnum(data.priority),

        # Planning
        delivery_deadline=data.delivery_deadline,
        earliest_delivery_date=data.earliest_delivery_date,
        flexibility_days=flexibility_days,

        # Auto-generated
        status=OrderStatusEnum.PENDING,
        tracking_token=tracking_token,
        source=OrderSourceEnum.PORTAL,
        attempts_count=0,
        special_instructions=data.special_instructions,
    )

    db.add(new_order)
    db.commit()
    db.refresh(new_order)

    return new_order


@router.get("/", response_model=list[OrderResponse])
def list_orders(
    status: str | None = Query(None, description="Filtrează pe status: PENDING, PLANNED, etc."),
    priority: str | None = Query(None, description="Filtrează pe prioritate: NORMAL, URGENT, CRITIC"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Listează comenzile.
    CLIENT vede doar comenzile lui. DISPECER/MANAGER vede tot din companie.
    """
    current_role = current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role)

    query = db.query(Order)

    if current_role == "CLIENT":
        query = query.filter(Order.client_id == current_user.id)
    else:
        query = query.filter(Order.company_id == current_user.company_id)

    if status:
        query = query.filter(Order.status == OrderStatusEnum(status))
    if priority:
        query = query.filter(Order.priority == PriorityEnum(priority))

    query = query.order_by(Order.delivery_deadline.asc())

    return query.all()


@router.get("/track/{tracking_token}", response_model=dict)
def track_order(
    tracking_token: str,
    db: Session = Depends(get_db),
):
    """Tracking public — fără autentificare."""
    order = db.query(Order).filter(Order.tracking_token == tracking_token).first()

    if not order:
        raise HTTPException(status_code=404, detail="Comanda nu a fost găsită")

    return {
        "order_ref": order.order_ref,
        "status": order.status.value if hasattr(order.status, 'value') else str(order.status),
        "delivery_deadline": str(order.delivery_deadline),
        "address_pickup": order.address_pickup,
        "address_delivery": order.address_delivery,
    }


@router.get("/{order_id}", response_model=OrderResponse)
def get_order(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returnează o comandă specifică."""
    current_role = current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role)

    query = db.query(Order).filter(Order.id == order_id)

    if current_role == "CLIENT":
        query = query.filter(Order.client_id == current_user.id)
    else:
        query = query.filter(Order.company_id == current_user.company_id)

    order = query.first()

    if not order:
        raise HTTPException(status_code=404, detail="Comanda nu a fost găsită")

    return order