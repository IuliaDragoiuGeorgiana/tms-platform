"""
Router pentru gestionarea incidentelor și recuperarea de comenzi.
"""

import uuid

from app.database import get_db
from app.dependencies import require_roles
from app.models.incident import Incident, IncidentTypeEnum
from app.models.trip_stop import TripStop
from app.models.user import User
from app.schemas.incident import (
    ImpactAnalysisResponse,
    IncidentListResponse,
    IncidentReportRequest,
    IncidentReportResponse,
    RecoverIncidentRequest,
    RecoverIncidentResponse,
)
from app.services.incident_service import report_incident
from app.services.recovery_service import (
    build_incident_recovery_analysis,
    create_recovery_trip,
    postpone_remaining_orders,
)
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

router = APIRouter(prefix="/incidents", tags=["Incidents"])


@router.get("/", response_model=list[IncidentListResponse])
def list_incidents(
    status_filter: str | None = Query(default="open", pattern="^(open|resolved|all)$"),
    type_filter: str | None = Query(default=None, pattern="^(MINOR|MAJOR)$"),
    current_user: User = Depends(require_roles("DISPECER", "MANAGER")),
    db: Session = Depends(get_db),
):
    """Listează incidentele companiei pentru manageri și dispeceri."""
    query = (
        db.query(Incident)
        .options(
            joinedload(Incident.trip),
            joinedload(Incident.driver),
            joinedload(Incident.vehicle),
        )
        .filter(Incident.trip.has(company_id=current_user.company_id))
    )

    if status_filter == "open":
        query = query.filter(Incident.resolved_at.is_(None))
    elif status_filter == "resolved":
        query = query.filter(Incident.resolved_at.is_not(None))

    if type_filter:
        query = query.filter(Incident.type == IncidentTypeEnum(type_filter))

    incidents = query.order_by(Incident.created_at.desc()).all()

    return [
        {
            "id": incident.id,
            "trip_id": incident.trip_id,
            "trip_status": incident.trip.status.value if incident.trip else None,
            "driver_id": incident.driver_id,
            "driver_name": (
                incident.driver.user.full_name
                if incident.driver and incident.driver.user
                else None
            ),
            "vehicle_id": incident.vehicle_id,
            "vehicle_plate": incident.vehicle.plate if incident.vehicle else None,
            "vehicle_status": incident.vehicle.status.value if incident.vehicle else None,
            "type": incident.type.value,
            "description": incident.description,
            "location_lat": incident.location_lat,
            "location_lon": incident.location_lon,
            "created_at": incident.created_at,
            "resolved_at": incident.resolved_at,
            "recovery_trip_id": incident.recovery_trip_id,
            "extra_cost_estimated": incident.extra_cost_estimated,
        }
        for incident in incidents
    ]


@router.post("/report", response_model=IncidentReportResponse)
def report_incident_endpoint(
    data: IncidentReportRequest,
    current_user: User = Depends(require_roles("SOFER")),
    db: Session = Depends(get_db),
):
    """Raportează un incident pentru un trip activ. Disponibil doar pentru șoferi."""
    return report_incident(
        db=db,
        current_user=current_user,
        trip_id=data.trip_id,
        incident_type=data.type,
        description=data.description,
        location_city=data.location_city,
        location_county=data.location_county,
        location_street=data.location_street,
        location_number=data.location_number,
    )


@router.get("/{incident_id}/impact-analysis", response_model=ImpactAnalysisResponse)
def get_impact_analysis(
    incident_id: uuid.UUID,
    current_user: User = Depends(require_roles("DISPECER", "MANAGER")),
    db: Session = Depends(get_db),
):
    """Returnează analiza reală de impact cu opțiuni optimizate."""
    incident = db.query(Incident).filter(Incident.id == incident_id).first()

    if not incident:
        raise HTTPException(status_code=404, detail="Incidentul nu a fost găsit")

    if not incident.trip:
        raise HTTPException(
            status_code=404, detail="Trip-ul asociat incidentului nu a fost găsit"
        )

    if incident.trip.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Nu ai acces la acest incident")

    if incident.type != IncidentTypeEnum.MAJOR:
        raise HTTPException(
            status_code=400,
            detail="Analiza de impact este disponibilă doar pentru incidente MAJOR",
        )

    if incident.trip.status.value != "INTERRUPTED":
        raise HTTPException(
            status_code=400,
            detail="Trip-ul original trebuie să fie INTERRUPTED",
        )

    analysis = build_incident_recovery_analysis(db, incident)
    incident.impact_analysis = analysis
    db.commit()

    return analysis


@router.post("/{incident_id}/recover", response_model=RecoverIncidentResponse)
def recover_incident(
    incident_id: uuid.UUID,
    data: RecoverIncidentRequest | None = None,
    current_user: User = Depends(require_roles("DISPECER", "MANAGER")),
    db: Session = Depends(get_db),
):
    """Creează recovery trip din opțiunea recomandată din impact analysis."""
    incident = db.query(Incident).filter(Incident.id == incident_id).first()

    if not incident:
        raise HTTPException(status_code=404, detail="Incidentul nu a fost găsit")

    if not incident.trip:
        raise HTTPException(
            status_code=404, detail="Trip-ul asociat incidentului nu a fost găsit"
        )

    if incident.trip.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Nu ai acces la acest incident")

    if incident.type != IncidentTypeEnum.MAJOR:
        raise HTTPException(
            status_code=400,
            detail="Recovery este disponibil doar pentru incidente MAJOR",
        )

    if incident.trip.status.value != "INTERRUPTED":
        raise HTTPException(
            status_code=400, detail="Trip-ul original trebuie să fie INTERRUPTED"
        )

    if incident.recovery_trip_id:
        raise HTTPException(
            status_code=400, detail="Acest incident are deja un recovery trip creat"
        )
    if incident.resolved_at:
        raise HTTPException(status_code=400, detail="Acest incident a fost deja tratat")

    if not incident.impact_analysis:
        raise HTTPException(status_code=400, detail="Impact analysis nu a fost generat")
    options = incident.impact_analysis.get("options", [])
    selected_option = None
    if data and data.option_id:
        selected_option = next(
            (option for option in options if option.get("option_id") == data.option_id),
            None,
        )
    elif data and data.strategy:
        selected_option = next(
            (
                option
                for option in options
                if option.get("type") == data.strategy and option.get("feasible")
            ),
            None,
        )
    else:
        selected_option = next(
            (option for option in options if option.get("recommended")), None
        )
    if not selected_option or not selected_option.get("feasible"):
        raise HTTPException(
            status_code=400, detail="Opțiunea de recovery selectată nu este fezabilă"
        )
    selected_strategy = selected_option["type"]
    if selected_strategy == "POSTPONE_REMAINING":
        postpone_result = postpone_remaining_orders(db=db, incident=incident)
        return {
            "message": "Comenzile nepreluate au fost trimise pentru replanificare.",
            "incident_id": incident.id,
            "original_trip_id": incident.trip_id,
            "recovery_trip_id": None,
            "planned_km": 0.0,
            "planned_duration_min": 0.0,
            "recovered_stops_count": 0,
            "recovered_orders_count": 0,
            "selected_strategy": selected_strategy,
            **postpone_result,
        }
    recovery_trip = create_recovery_trip(
        db=db, incident=incident, selected_option=selected_option
    )
    recovery_stops = (
        db.query(TripStop).filter(TripStop.trip_id == recovery_trip.id).all()
    )
    affected_order_ids = {stop.order_id for stop in recovery_stops}
    return {
        "message": "Recovery trip creat cu succes din opțiunea selectată.",
        "incident_id": incident.id,
        "original_trip_id": incident.trip_id,
        "recovery_trip_id": recovery_trip.id,
        "planned_km": recovery_trip.planned_km,
        "planned_duration_min": recovery_trip.planned_duration_min,
        "recovered_stops_count": len(recovery_stops),
        "recovered_orders_count": len(affected_order_ids),
        "selected_strategy": selected_strategy,
        "postponed_orders_count": 0,
        "postponed_order_refs": [],
    }
