from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, timezone
import uuid

from app.database import get_db
from app.models.user import User
from app.models.trip import Trip, TripStatusEnum
from app.models.trip_stop import TripStop, StopStatusEnum, StopTypeEnum, FailureReasonEnum
from app.models.order import Order, OrderStatusEnum
from app.schemas.trip import TripResponse, TripStopResponse, CompleteStopRequest, FailStopRequest
from app.dependencies import require_roles, get_current_user

router = APIRouter(prefix="/trips", tags=["Trips"])


# ==========================================
# VIZUALIZARE CURSE
# ==========================================

@router.get("/", response_model=list[TripResponse])
def list_trips(
    status_filter: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Listează cursele.
    DISPECER/MANAGER: vede toate cursele din companie.
    SOFER: vede doar cursele lui.
    """
    current_role = current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role)

    query = db.query(Trip).filter(Trip.company_id == current_user.company_id)

    # Șoferul vede doar cursele lui
    if current_role == "SOFER":
        from app.models.driver import Driver
        driver = db.query(Driver).filter(Driver.user_id == current_user.id).first()
        if not driver:
            raise HTTPException(status_code=404, detail="Nu ai profil de șofer")
        query = query.filter(Trip.driver_id == driver.id)

    if status_filter:
        query = query.filter(Trip.status == TripStatusEnum(status_filter))

    query = query.order_by(Trip.planned_date.desc())

    return query.all()


@router.get("/{trip_id}", response_model=TripResponse)
def get_trip(
    trip_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returnează o cursă specifică."""
    trip = db.query(Trip).filter(
        Trip.id == trip_id,
        Trip.company_id == current_user.company_id,
    ).first()

    if not trip:
        raise HTTPException(status_code=404, detail="Cursa nu a fost găsită")

    return trip


@router.get("/{trip_id}/stops", response_model=list[TripStopResponse])
def get_trip_stops(
    trip_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returnează stopurile unei curse în ordine.
    Șoferul vede lista: pickup 1, pickup 2, delivery 1, delivery 2 etc.
    """
    trip = db.query(Trip).filter(
        Trip.id == trip_id,
        Trip.company_id == current_user.company_id,
    ).first()

    if not trip:
        raise HTTPException(status_code=404, detail="Cursa nu a fost găsită")

    stops = db.query(TripStop).filter(
        TripStop.trip_id == trip_id
    ).order_by(TripStop.sequence).all()

    return stops


# ==========================================
# APROBARE CURSĂ (DISPECER/MANAGER)
# ==========================================

@router.patch("/{trip_id}/approve", response_model=TripResponse)
def approve_trip(
    trip_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("DISPECER", "MANAGER")),
):
    """
    Dispecerul aprobă o cursă propusă de algoritm.
    PROPOSED → APPROVED. Acum șoferul o poate vedea și porni.
    """
    trip = db.query(Trip).filter(
        Trip.id == trip_id,
        Trip.company_id == current_user.company_id,
    ).first()

    if not trip:
        raise HTTPException(status_code=404, detail="Cursa nu a fost găsită")

    if trip.status != TripStatusEnum.PROPOSED:
        raise HTTPException(
            status_code=400,
            detail=f"Cursa are statusul {trip.status.value}, nu PROPOSED"
        )

    trip.status = TripStatusEnum.APPROVED
    db.commit()
    db.refresh(trip)

    return trip


# ==========================================
# EXECUȚIE CURSĂ (SOFER)
# ==========================================

@router.patch("/{trip_id}/start", response_model=TripResponse)
def start_trip(
    trip_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("SOFER")),
):
    """
    Șoferul pornește cursa. APPROVED → IN_PROGRESS.
    Marchează ora reală de plecare.
    """
    from app.models.driver import Driver
    driver = db.query(Driver).filter(Driver.user_id == current_user.id).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Nu ai profil de șofer")

    trip = db.query(Trip).filter(
        Trip.id == trip_id,
        Trip.driver_id == driver.id,
    ).first()

    if not trip:
        raise HTTPException(status_code=404, detail="Cursa nu a fost găsită sau nu ți-e alocată")

    if trip.status != TripStatusEnum.APPROVED:
        raise HTTPException(
            status_code=400,
            detail=f"Cursa are statusul {trip.status.value}, nu APPROVED"
        )

    trip.status = TripStatusEnum.IN_PROGRESS
    trip.started_at = datetime.now(timezone.utc)

    # Actualizează statusul comenzilor la IN_DELIVERY
    for stop in trip.stops:
        if stop.stop_type == StopTypeEnum.PICKUP:
            stop.order.status = OrderStatusEnum.IN_DELIVERY

    db.commit()
    db.refresh(trip)

    return trip


@router.patch("/{trip_id}/stops/{stop_id}/arrive", response_model=TripStopResponse)
def arrive_at_stop(
    trip_id: uuid.UUID,
    stop_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("SOFER")),
):
    """
    Șoferul a ajuns la stop. Marchează ora de sosire.
    E ca un check-in: "am ajuns la adresă".
    """
    from app.models.driver import Driver
    driver = db.query(Driver).filter(Driver.user_id == current_user.id).first()

    trip = db.query(Trip).filter(
        Trip.id == trip_id,
        Trip.driver_id == driver.id,
    ).first()

    if not trip or trip.status != TripStatusEnum.IN_PROGRESS:
        raise HTTPException(status_code=400, detail="Cursa nu e în desfășurare")

    stop = db.query(TripStop).filter(
        TripStop.id == stop_id,
        TripStop.trip_id == trip_id,
    ).first()

    if not stop:
        raise HTTPException(status_code=404, detail="Stopul nu a fost găsit")

    if stop.status != StopStatusEnum.PENDING:
        raise HTTPException(status_code=400, detail=f"Stopul are deja statusul {stop.status.value}")

    stop.arrival_time = datetime.now(timezone.utc)
    stop.eta_actual = datetime.now(timezone.utc)
    db.commit()
    db.refresh(stop)

    return stop


@router.patch("/{trip_id}/stops/{stop_id}/complete", response_model=TripStopResponse)
def complete_stop(
    trip_id: uuid.UUID,
    stop_id: uuid.UUID,
    data: CompleteStopRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("SOFER")),
):
    """
    Șoferul confirmă finalizarea stopului.
    PICKUP: marfa a fost preluată cu succes.
    DELIVERY: marfa a fost livrată cu succes.
    """
    from app.models.driver import Driver
    driver = db.query(Driver).filter(Driver.user_id == current_user.id).first()

    trip = db.query(Trip).filter(
        Trip.id == trip_id,
        Trip.driver_id == driver.id,
    ).first()

    if not trip or trip.status != TripStatusEnum.IN_PROGRESS:
        raise HTTPException(status_code=400, detail="Cursa nu e în desfășurare")

    stop = db.query(TripStop).filter(
        TripStop.id == stop_id,
        TripStop.trip_id == trip_id,
    ).first()

    if not stop:
        raise HTTPException(status_code=404, detail="Stopul nu a fost găsit")

    if stop.status != StopStatusEnum.PENDING:
        raise HTTPException(status_code=400, detail=f"Stopul are deja statusul {stop.status.value}")

    stop.status = StopStatusEnum.DELIVERED
    stop.departure_time = datetime.now(timezone.utc)
    stop.notes = data.notes

    if not stop.arrival_time:
        stop.arrival_time = datetime.now(timezone.utc)

    # Dacă e DELIVERY și a fost livrat cu succes, marcăm comanda DELIVERED
    if stop.stop_type == StopTypeEnum.DELIVERY:
        stop.order.status = OrderStatusEnum.DELIVERED

    db.commit()
    db.refresh(stop)

    return stop


@router.patch("/{trip_id}/stops/{stop_id}/fail", response_model=TripStopResponse)
def fail_stop(
    trip_id: uuid.UUID,
    stop_id: uuid.UUID,
    data: FailStopRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("SOFER")),
):
    """
    Șoferul raportează eșec la un stop.
    Motivele: ABSENT, REFUSED, WRONG_ADDRESS, DAMAGED, OTHER.
    
    Dacă PICKUP eșuează → DELIVERY-ul aceleiași comenzi devine SKIPPED automat.
    Dacă DELIVERY eșuează → comanda revine FAILED, reintrare în order pool.
    """
    from app.models.driver import Driver
    driver = db.query(Driver).filter(Driver.user_id == current_user.id).first()

    trip = db.query(Trip).filter(
        Trip.id == trip_id,
        Trip.driver_id == driver.id,
    ).first()

    if not trip or trip.status != TripStatusEnum.IN_PROGRESS:
        raise HTTPException(status_code=400, detail="Cursa nu e în desfășurare")

    stop = db.query(TripStop).filter(
        TripStop.id == stop_id,
        TripStop.trip_id == trip_id,
    ).first()

    if not stop:
        raise HTTPException(status_code=404, detail="Stopul nu a fost găsit")

    if stop.status != StopStatusEnum.PENDING:
        raise HTTPException(status_code=400, detail=f"Stopul are deja statusul {stop.status.value}")

    stop.status = StopStatusEnum.FAILED
    stop.failure_reason = FailureReasonEnum(data.failure_reason)
    stop.notes = data.notes
    stop.departure_time = datetime.now(timezone.utc)

    if not stop.arrival_time:
        stop.arrival_time = datetime.now(timezone.utc)

    # Dacă pickup eșuează, skip automat delivery-ul aceleiași comenzi
    if stop.stop_type == StopTypeEnum.PICKUP:
        delivery_stop = db.query(TripStop).filter(
            TripStop.trip_id == trip_id,
            TripStop.order_id == stop.order_id,
            TripStop.stop_type == StopTypeEnum.DELIVERY,
        ).first()

        if delivery_stop and delivery_stop.status == StopStatusEnum.PENDING:
            delivery_stop.status = StopStatusEnum.SKIPPED
            delivery_stop.notes = "Skipped automat — pickup eșuat"

    # Comanda devine FAILED
    stop.order.status = OrderStatusEnum.FAILED
    stop.order.attempts_count += 1

    db.commit()
    db.refresh(stop)

    return stop


# ==========================================
# FINALIZARE CURSĂ (SOFER)
# ==========================================

@router.patch("/{trip_id}/complete", response_model=TripResponse)
def complete_trip(
    trip_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("SOFER")),
):
    """
    Șoferul finalizează cursa. IN_PROGRESS → COMPLETED.
    Se calculează durata reală și km reali.
    """
    from app.models.driver import Driver
    driver = db.query(Driver).filter(Driver.user_id == current_user.id).first()

    trip = db.query(Trip).filter(
        Trip.id == trip_id,
        Trip.driver_id == driver.id,
    ).first()

    if not trip:
        raise HTTPException(status_code=404, detail="Cursa nu a fost găsită")

    if trip.status != TripStatusEnum.IN_PROGRESS:
        raise HTTPException(
            status_code=400,
            detail=f"Cursa are statusul {trip.status.value}, nu IN_PROGRESS"
        )

    # Verifică că toate stopurile sunt finalizate
    pending_stops = db.query(TripStop).filter(
        TripStop.trip_id == trip_id,
        TripStop.status == StopStatusEnum.PENDING,
    ).count()

    if pending_stops > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Mai ai {pending_stops} stopuri nefinalizate"
        )

    trip.status = TripStatusEnum.COMPLETED
    trip.completed_at = datetime.now(timezone.utc)

    # Calculează durata reală
    if trip.started_at:
        duration = trip.completed_at - trip.started_at
        trip.actual_duration_min = int(duration.total_seconds() / 60)

    db.commit()
    db.refresh(trip)

    return trip