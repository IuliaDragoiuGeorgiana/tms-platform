"""
Router pentru Analytics endpoints - Business insights și planning intelligence.
"""
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_roles
from app.models.user import User
from app.schemas.analytics import (
    ZoneDemandResponse,
    DriverZoneFitResponse,
    VehicleTripFitResponse,
    FleetUtilizationResponse,
    PlanningQualityResponse,
    UnplannedOrdersResponse,
    PlanVsActualResponse,
    ServiceTimeAccuracyResponse,
    CostAnalyticsResponse,
    IncidentImpactResponse,
)
from app.services import analytics_service

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/health")
def health_check():
    """
    Health check endpoint pentru analytics module.
    """
    return {
        "status": "ok",
        "module": "analytics",
        "endpoints": 10,
    }


@router.get("/zone-demand", response_model=ZoneDemandResponse)
def get_zone_demand(
    start_date: date = Query(None),
    end_date: date = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("MANAGER", "DISPECER")),
):
    """
    Identifică zonele cu cerere mare și generează recomandări de planificare.

    Parametri:
    - start_date: Data de început (optional, default: ultimele 30 de zile)
    - end_date: Data de sfârșit (optional, default: azi)

    Returnează score de cerere per zonă și recomandări.
    """
    result = analytics_service.get_zone_demand(db, current_user.company_id, start_date, end_date)
    return result


@router.get("/driver-zone-fit", response_model=DriverZoneFitResponse)
def get_driver_zone_fit(
    zone: str = Query(..., description="Zona de evaluare (ex: Timisoara)"),
    start_date: date = Query(None),
    end_date: date = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("MANAGER", "DISPECER")),
):
    """
    Recomandă șoferi potriviți pentru o zonă pe baza performanței istorice.

    Parametri:
    - zone: Zona pentru care se caută șoferi (obligatoriu)
    - start_date: Data de început (optional, default: ultimele 30 de zile)
    - end_date: Data de sfârșit (optional, default: azi)

    Returnează top 10 șoferi cu scoruri și motive de recomandare.
    """
    result = analytics_service.get_driver_zone_fit(db, current_user.company_id, zone, start_date, end_date)
    return result


@router.get("/vehicle-trip-fit", response_model=VehicleTripFitResponse)
def get_vehicle_trip_fit(
    trip_id: str = Query(None, description="ID-ul cursă (optional)"),
    order_ids: str = Query(None, description="ID-uri comenzi separate prin virgulă (optional)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("MANAGER", "DISPECER")),
):
    """
    Recomandă vehicule potrivite pentru o cursă sau set de comenzi.

    Parametri:
    - trip_id: ID-ul cursă (optional, dacă nu se trimit comenzi)
    - order_ids: ID-uri comenzi separate prin virgulă (optional)

    Notă: Trebuie trimis fie trip_id, fie order_ids.

    Returnează vehiculele recomandate cu scoruri și motive.
    """
    if not trip_id and not order_ids:
        raise HTTPException(status_code=400, detail="Trebuie trimis fie trip_id, fie order_ids")

    order_ids_list = None
    if order_ids:
        order_ids_list = [oid.strip() for oid in order_ids.split(",")]

    result = analytics_service.get_vehicle_trip_fit(db, current_user.company_id, trip_id, order_ids_list)
    if "error" in result:
        status_code = 404 if "not found" in result["error"].lower() else 400
        raise HTTPException(status_code=status_code, detail=result["error"])

    return result


@router.get("/fleet-utilization", response_model=FleetUtilizationResponse)
def get_fleet_utilization(
    start_date: date = Query(None),
    end_date: date = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("MANAGER", "DISPECER")),
):
    """
    Analizează utilizarea flotei și identifică curse subutilizate.

    Parametri:
    - start_date: Data de început (optional, default: ultimele 30 de zile)
    - end_date: Data de sfârșit (optional, default: azi)

    Returnează statistici per cursă și summary de utilizare.
    """
    result = analytics_service.get_fleet_utilization(db, current_user.company_id, start_date, end_date)
    return result


@router.get("/planning-quality/{planning_session_id}", response_model=PlanningQualityResponse)
def get_planning_quality(
    planning_session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("MANAGER", "DISPECER")),
):
    """
    Evaluează calitatea unei sesiuni de planificare.

    Parametri:
    - planning_session_id: ID-ul sesiunii de planificare (obligatoriu, în URL)

    Returnează score de calitate și recomandări de îmbunătățire.
    """
    result = analytics_service.get_planning_quality(db, current_user.company_id, planning_session_id)

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return result


@router.get("/unplanned-orders", response_model=UnplannedOrdersResponse)
def get_unplanned_orders(
    start_date: date = Query(None),
    end_date: date = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("MANAGER", "DISPECER")),
):
    """
    Analizează comenzile neplanificate și motivele.

    Parametri:
    - start_date: Data de început (optional, default: ultimele 30 de zile)
    - end_date: Data de sfârșit (optional, default: azi)

    Returnează contoare per motiv și recomandări.
    """
    result = analytics_service.get_unplanned_orders(db, current_user.company_id, start_date, end_date)
    return result


@router.get("/plan-vs-actual", response_model=PlanVsActualResponse)
def get_plan_vs_actual(
    start_date: date = Query(None),
    end_date: date = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("MANAGER", "DISPECER")),
):
    """
    Compară planificarea cu execuția reală.

    Parametri:
    - start_date: Data de început (optional, default: ultimele 30 de zile)
    - end_date: Data de sfârșit (optional, default: azi)

    Returnează abaterile și performanța per șofer, vehicul și zonă.
    """
    result = analytics_service.get_plan_vs_actual(db, current_user.company_id, start_date, end_date)
    return result


@router.get("/service-time-accuracy", response_model=ServiceTimeAccuracyResponse)
def get_service_time_accuracy(
    start_date: date = Query(None),
    end_date: date = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("MANAGER", "DISPECER")),
):
    """
    Analizează acuratețea service time-ului și sugerează ajustări.

    Parametri:
    - start_date: Data de început (optional, default: ultimele 30 de zile)
    - end_date: Data de sfârșit (optional, default: azi)

    Returnează devieri per tip de marfă, zonă și tip de stop.
    """
    result = analytics_service.get_service_time_accuracy(db, current_user.company_id, start_date, end_date)
    return result


@router.get("/costs", response_model=CostAnalyticsResponse)
def get_costs(
    start_date: date = Query(None),
    end_date: date = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("MANAGER", "DISPECER")),
):
    """
    Analizează costurile operaționale și identifică oportunitățile de optimizare.

    Parametri:
    - start_date: Data de început (optional, default: ultimele 30 de zile)
    - end_date: Data de sfârșit (optional, default: azi)

    Returnează KPI-uri de cost și breakdown per dimensiune.
    """
    result = analytics_service.get_costs(db, current_user.company_id, start_date, end_date)
    return result


@router.get("/incident-impact", response_model=IncidentImpactResponse)
def get_incident_impact(
    start_date: date = Query(None),
    end_date: date = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("MANAGER", "DISPECER")),
):
    """
    Analizează impactul incidentelor și eficiența recovery-ului.

    Parametri:
    - start_date: Data de început (optional, default: ultimele 30 de zile)
    - end_date: Data de sfârșit (optional, default: azi)

    Returnează statistici de incidente și detalii asupra impactului major.
    """
    result = analytics_service.get_incident_impact(db, current_user.company_id, start_date, end_date)
    return result
