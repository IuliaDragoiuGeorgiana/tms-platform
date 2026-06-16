from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import date, timedelta
from sqlalchemy import or_
import uuid

from app.database import get_db
from app.models.user import User
from app.dependencies import require_roles
from app.services.planning_service import (
    run_planning,
    change_trip_driver,
    change_trip_vehicle,
    remove_order_from_trip,
    add_order_to_trip,
)
from app.schemas.planning import (
    EligibleOrdersRequest,
    EligibleOrderSummary,
    EligibleOrdersResponse,
    GeneratePlanRequest,
    ChangeDriverRequest,
    ChangeVehicleRequest,
    AddOrderToTripRequest,
)
from app.models.order import Order, OrderStatusEnum
from app.models.planning_session import PlanningStrategyEnum, PlanningSession, PlanningStatusEnum
from app.models.trip import Trip, TripStatusEnum

router = APIRouter(prefix="/planning", tags=["Planning"])


@router.post("/generate", status_code=status.HTTP_201_CREATED)
def generate_plan(
    planned_date: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("DISPECER", "MANAGER")),
):
    """
    Generează un plan de livrare pentru o zi specifică.
    
    Pipeline complet:
    1. Ia comenzile PENDING din compania ta
    2. Geocodează adresele care nu au coordonate GPS
    3. Calculează câte curse sunt necesare (K-means clustering)
    4. Optimizează ordinea stopurilor per cursă (OR-Tools VRP)
    5. Calculează ETA per stop
    6. Salvează totul în DB (PlanningSession + Trips + TripStops)
    
    Doar DISPECER și MANAGER pot genera planuri.
    """
    if planned_date < date.today():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nu poți genera un plan pentru o dată din trecut",
        )
    result = run_planning(
        db=db,
        company_id=current_user.company_id,
        planned_date=planned_date,
        created_by_id=current_user.id,
    )

    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"],
        )

    return result

@router.post("/eligible-orders", response_model=EligibleOrdersResponse)
def get_eligible_orders(
    body: EligibleOrdersRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("DISPECER", "MANAGER")),
):
    """
    Returnează comenzile eligibile pentru planificare într-un interval de date.
 
    Dispecerul trimite date_start și date_end, și primește înapoi
    lista de comenzi PENDING care pot fi livrate în acel interval.
 
    O comandă e eligibilă dacă:
    1. E PENDING (nu e deja planificată, livrată sau anulată)
    2. Nu e marcată ca problematică
    3. Are delivery_deadline în intervalul cerut
       SAU are flexibility_days care îi permite livrare în acel interval
    4. Earliest_delivery_date (dacă există) permite livrarea în interval
    """
 
    # Validare: nu poți planifica în trecut
    if body.date_start < date.today():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nu poți planifica pentru o dată din trecut",
        )
 
    # Validare: intervalul nu poate fi mai mare de 7 zile
    max_days = 7
    if (body.date_end - body.date_start).days >= max_days:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Intervalul nu poate depăși {max_days} zile",
        )
 
    # Ia toate comenzile PENDING, neproblematice, din compania dispecerului
    orders = db.query(Order).filter(
        Order.company_id == current_user.company_id,
        Order.status == OrderStatusEnum.PENDING,
        Order.is_problematic.is_(False),
    ).all()
 
    # Filtrare în Python pentru logica de eligibilitate cu flexibility_days
    eligible = []
 
    for order in orders:
        # Calculează intervalul în care comanda poate fi livrată
        # Exemplu: deadline = 20 iunie, flexibility = 3
        #   → poate fi livrată între 17 iunie și 20 iunie
        order_earliest = order.delivery_deadline - timedelta(
            days=order.flexibility_days
        )
 
        if order.earliest_delivery_date:
            order_earliest = max(order_earliest, order.earliest_delivery_date)
 
        order_latest = order.delivery_deadline
 
        # Verifică dacă intervalul comenzii se suprapune cu intervalul cerut
        if order_earliest <= body.date_end and order_latest >= body.date_start:
            eligible.append(order)
 
    # Construiește răspunsul
    order_summaries = []
    by_priority = {"CRITIC": 0, "URGENT": 0, "NORMAL": 0}
 
    for order in eligible:
        client_name = None
        if order.client:
            client_name = order.client.full_name
 
        priority_value = (
            order.priority.value
            if hasattr(order.priority, "value")
            else str(order.priority)
        )
        type_marfa_value = (
            order.type_marfa.value
            if hasattr(order.type_marfa, "value")
            else str(order.type_marfa)
        )
 
        if priority_value in by_priority:
            by_priority[priority_value] += 1
 
        order_summaries.append(EligibleOrderSummary(
            id=order.id,
            order_ref=order.order_ref,
            client_name=client_name,
            address_pickup=order.address_pickup,
            address_delivery=order.address_delivery,
            kg=float(order.kg),
            m3=float(order.m3),
            type_marfa=type_marfa_value,
            priority=priority_value,
            delivery_deadline=order.delivery_deadline,
            earliest_delivery_date=order.earliest_delivery_date,
            flexibility_days=order.flexibility_days,
            pickup_time_window_start=order.pickup_time_window_start,
            pickup_time_window_end=order.pickup_time_window_end,
            delivery_time_window_start=order.delivery_time_window_start,
            delivery_time_window_end=order.delivery_time_window_end,
        ))
 
    # Sortează: CRITIC primele, apoi URGENT, apoi NORMAL, apoi deadline
    priority_order = {"CRITIC": 0, "URGENT": 1, "NORMAL": 2}
    order_summaries.sort(
        key=lambda o: (priority_order.get(o.priority, 2), o.delivery_deadline)
    )
 
    return EligibleOrdersResponse(
        date_start=body.date_start,
        date_end=body.date_end,
        total_eligible=len(order_summaries),
        total_kg=round(sum(o.kg for o in order_summaries), 2),
        total_m3=round(sum(o.m3 for o in order_summaries), 2),
        by_priority=by_priority,
        orders=order_summaries,
    )

@router.post("/compare-strategies")
def compare_strategies(
    body: EligibleOrdersRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("DISPECER", "MANAGER")),
):
    if body.date_start < date.today():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nu poți planifica pentru o dată din trecut",
        )

    if body.date_end < body.date_start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Data de final nu poate fi înaintea datei de început",
        )

    # Warm-up: rulează o planificare dry-run ca să se facă geocodarea
    # și să se salveze coordonatele lipsă înainte de comparația strategiilor.
    warmup_result = run_planning(
        db=db,
        company_id=current_user.company_id,
        planned_date=body.date_start,
        created_by_id=current_user.id,
        strategy=PlanningStrategyEnum.GREEDY_DEADLINE,
        dry_run=True,
        date_start=body.date_start,
        date_end=body.date_end,
    )

    if "error" in warmup_result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=warmup_result["error"],
        )

    db.expire_all()

    strategies = [
        PlanningStrategyEnum.GREEDY_DEADLINE,
        PlanningStrategyEnum.MAX_DENSITY,
        PlanningStrategyEnum.HYBRID,
    ]

    variants = []

    for strategy in strategies:
        result = run_planning(
            db=db,
            company_id=current_user.company_id,
            planned_date=body.date_start,
            created_by_id=current_user.id,
            strategy=strategy,
            dry_run=True,
            date_start=body.date_start,
            date_end=body.date_end,
        )

        if "error" in result:
            variants.append({
                "strategy": strategy.value,
                "error": result["error"],
            })
        else:
            variants.append({
                "strategy": result.get("strategy"),
                "total_orders": result.get("total_orders"),
                "total_planned": result.get("total_planned"),
                "total_dropped": result.get("total_dropped"),
                "total_trips": result.get("total_trips"),
                "total_km": result.get("total_km"),
                "total_minutes": result.get("total_minutes"),
                "feasibility": result.get("feasibility"),
                "orders_on_time": result.get("orders_on_time"),
                "delayed_orders_count": result.get("delayed_orders_count"),
                "warnings_count": result.get("warnings_count"),
                "trips": result.get("trips"),
                "warnings": result.get("warnings"),
                "dropped_orders": result.get("dropped_orders"),
                "cluster_debug_by_day": result.get("cluster_debug_by_day", []),
            })

    return {
        "date_start": str(body.date_start),
        "date_end": str(body.date_end),
        "variants": variants,
    }
 
@router.post("/generate-with-strategy", status_code=status.HTTP_201_CREATED)
def generate_with_strategy(
    body: GeneratePlanRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("DISPECER", "MANAGER")),
):
    """
    Generează planul real cu strategia aleasă de dispecer.
 
    Apelat după ce dispecerul a comparat strategiile cu
    POST /planning/compare-strategies și a ales una.
 
    Salvează planul în DB ca PROPOSED.
    """
    if body.date_start < date.today():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nu poți planifica pentru o dată din trecut",
        )
 
    # Convertește string-ul strategiei în enum
    strategy_map = {
        "GREEDY_DEADLINE": PlanningStrategyEnum.GREEDY_DEADLINE,
        "MAX_DENSITY": PlanningStrategyEnum.MAX_DENSITY,
        "HYBRID": PlanningStrategyEnum.HYBRID,
    }
    strategy_value = body.strategy.value if hasattr(body.strategy, "value") else str(body.strategy)
    strategy_enum = strategy_map.get(strategy_value)
    if not strategy_enum:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Strategie invalidă: {body.strategy}",
        )
 
    result = run_planning(
        db=db,
        company_id=current_user.company_id,
        planned_date=body.date_start,
        created_by_id=current_user.id,
        strategy=strategy_enum,
        dry_run=False,
        date_start=body.date_start,
        date_end=body.date_end,
    )
 
    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"],
        )

    return result


@router.post("/sessions/{session_id}/approve", status_code=status.HTTP_200_OK)
def approve_planning_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("DISPECER", "MANAGER")),
):
    session = db.query(PlanningSession).filter(
        PlanningSession.id == session_id,
        PlanningSession.company_id == current_user.company_id,
    ).first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sesiunea de planificare nu a fost găsită",
        )

    if session.status != PlanningStatusEnum.PROPOSED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Sesiunea nu este în stare PROPOSED. Status actual: {session.status.value}",
        )

    trips = db.query(Trip).filter(
        Trip.planning_session_id == session_id,
        Trip.company_id == current_user.company_id,
        Trip.status == TripStatusEnum.PROPOSED,
    ).all()

    if not trips:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sesiunea nu are curse PROPOSED care pot fi aprobate",
        )

    session.status = PlanningStatusEnum.APPROVED

    for trip in trips:
        trip.status = TripStatusEnum.APPROVED

    db.commit()
    db.refresh(session)

    return {
        "planning_session_id": str(session.id),
        "status": session.status.value,
        "date_range_start": str(session.date_range_start),
        "date_range_end": str(session.date_range_end),
        "strategy": session.strategy.value,
        "total_orders": session.total_orders,
        "trips_approved": len(trips),
        "message": f"Sesiunea de planificare a fost aprobată. {len(trips)} curse sunt acum vizibile șoferilor.",
    }


@router.patch("/trips/{trip_id}/driver", status_code=status.HTTP_200_OK)
def change_driver_on_trip(
    trip_id: uuid.UUID,
    body: ChangeDriverRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("DISPECER", "MANAGER")),
):
    """
    Validări:
    - Trip-ul este PROPOSED
    - PlanningSession este PROPOSED
    - Noul șofer există, e AVAILABLE, aparține aceleiași companii
    - Trip-ul se încadrează în programul de lucru al șoferului
    - Șoferul nu are alt trip care se suprapune orar

    Ruta nu se modifică — doar alocarea șoferului.
    """
    try:
        result = change_trip_driver(
            db=db,
            trip_id=trip_id,
            new_driver_id=body.driver_id,
            company_id=current_user.company_id,
        )
        return result
    except ValueError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.patch("/trips/{trip_id}/vehicle", status_code=status.HTTP_200_OK)
def change_vehicle_on_trip(
    trip_id: uuid.UUID,
    body: ChangeVehicleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("DISPECER", "MANAGER")),
):
    """
    Schimbă vehiculul pe un trip din sesiune PROPOSED.

    Validări:
    - Trip-ul este PROPOSED
    - PlanningSession este PROPOSED
    - Noul vehicul există, e DISPONIBIL, aparține aceleiași companii
    - Noul vehicul poate susține încărcarea maximă simultană pe ordinea stopurilor:
    PICKUP = adaugă kg/m3, DELIVERY = scade kg/m3
    """
    try:
        result = change_trip_vehicle(
            db=db,
            trip_id=trip_id,
            new_vehicle_id=body.vehicle_id,
            company_id=current_user.company_id,
        )
        return result
    except ValueError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.delete("/trips/{trip_id}/orders/{order_id}", status_code=status.HTTP_200_OK)
def remove_order_from_trip_endpoint(
    trip_id: uuid.UUID,
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("DISPECER", "MANAGER")),
):
    """
    Scoate o comandă dintr-un trip PROPOSED și reoptimizează ruta rămasă.

    Efecte:
    - comanda scoasă revine în PENDING;
    - assigned_delivery_date devine NULL;
    - stopurile trip-ului sunt regenerate;
    - planned_km și planned_duration_min sunt recalculate;
    - ETA-urile sunt recalculate;
    - dacă trip-ul rămâne fără comenzi, trip-ul este șters.
    """
    try:
        result = remove_order_from_trip(
            db=db,
            trip_id=trip_id,
            order_id=order_id,
            company_id=current_user.company_id,
        )
        return result

    except ValueError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/trips/{trip_id}/orders", status_code=status.HTTP_200_OK)
def add_order_to_trip_endpoint(
    trip_id: uuid.UUID,
    body: AddOrderToTripRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("DISPECER", "MANAGER")),
):
    """
    Adaugă o comandă PENDING într-un trip PROPOSED și reoptimizează ruta.

    Validări:
    - Trip-ul este PROPOSED
    - PlanningSession este PROPOSED
    - Comanda este PENDING
    - Comanda nu este problematică
    - Comanda nu este deja în trip
    - Comanda este eligibilă pentru data trip-ului
    - Ruta cu noua comandă este fezabilă pentru același vehicul și șofer

    Dacă vreo validare eșuează, operația este refuzată și nu se modifică nimic.
    """
    try:
        result = add_order_to_trip(
            db=db,
            trip_id=trip_id,
            order_id=body.order_id,
            company_id=current_user.company_id,
        )
        return result

    except ValueError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )