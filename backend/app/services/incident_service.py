"""
Serviciul de gestionare a incidentelor — raportare, analiză și recuperare.
"""
from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.models.incident import Incident, IncidentTypeEnum
from app.models.trip import Trip, TripStatusEnum
from app.models.vehicle import Vehicle, VehicleStatusEnum
from app.models.driver import Driver
from app.models.user import User
from app.services.ors_service import geocode


def report_incident(
    db: Session,
    current_user: User,
    trip_id,
    incident_type: str,
    description: str,
    location_city: str,
    location_county: str,
    location_street: str,
    location_number: str,
):
    """
    Raportează un incident pentru un trip activ.

    Doar șoferul care conduce trip-ul poate raporta incident pentru acel trip.
    Dacă incident-ul este MAJOR, trip-ul devine INTERRUPTED și vehiculul devine AVARIAT.
    """
    trip = db.query(Trip).filter(Trip.id == trip_id).first()

    if not trip:
        raise HTTPException(status_code=404, detail="Trip-ul nu a fost găsit")

    if trip.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Nu ai acces la acest trip")

    driver = db.query(Driver).filter(
        Driver.user_id == current_user.id,
        Driver.company_id == current_user.company_id,
    ).first()

    if not driver:
        raise HTTPException(status_code=403, detail="Nu ai profil de șofer")

    if trip.driver_id != driver.id:
        raise HTTPException(
            status_code=403,
            detail="Poți raporta incident doar pentru trip-ul tău",
        )

    if trip.status != TripStatusEnum.IN_PROGRESS:
        raise HTTPException(
            status_code=400,
            detail="Trip-ul nu este în curs de desfășurare",
        )

    if not trip.vehicle_id:
        raise HTTPException(
            status_code=400,
            detail="Trip-ul nu are vehicul asociat",
        )

    vehicle = db.query(Vehicle).filter(
        Vehicle.id == trip.vehicle_id,
        Vehicle.company_id == current_user.company_id,
    ).first()

    if not vehicle:
        raise HTTPException(
            status_code=400,
            detail="Vehiculul asociat trip-ului nu a fost găsit",
        )

    try:
        incident_enum = IncidentTypeEnum(incident_type.upper())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Tip incident invalid. Folosește MINOR sau MAJOR",
        )

    location_parts = (
        location_street,
        location_number,
        location_city,
        location_county,
    )
    clean_location_parts = tuple(part.strip() for part in location_parts)
    if not all(clean_location_parts):
        raise HTTPException(
            status_code=422,
            detail=dict(location_parts=clean_location_parts, required=True),
        )

    location = f"{clean_location_parts[0]} {clean_location_parts[1]}, {clean_location_parts[2]}, {clean_location_parts[3]}"
    coordinates = geocode(location)
    if not coordinates:
        raise HTTPException(
            status_code=422,
            detail=dict(location=location, geocoded=False),
        )

    latitude = coordinates["lat"]
    longitude = coordinates["lon"]
    incident = Incident(
        trip_id=trip.id,
        driver_id=driver.id,
        vehicle_id=vehicle.id,
        type=incident_enum,
        description=description,
        location_lat=latitude,
        location_lon=longitude,
    )

    if incident_enum == IncidentTypeEnum.MAJOR:
        trip.status = TripStatusEnum.INTERRUPTED
        vehicle.status = VehicleStatusEnum.AVARIAT
        message = "Incident major raportat. Cursa a fost întreruptă, iar vehiculul a fost marcat ca avariat."
    else:
        message = "Incident minor raportat cu succes."

    db.add(incident)
    db.commit()

    db.refresh(incident)
    db.refresh(trip)
    db.refresh(vehicle)

    return {
        "message": message,
        "incident_id": incident.id,
        "trip_id": trip.id,
        "trip_status": trip.status.value,
        "vehicle_id": vehicle.id,
        "vehicle_status": vehicle.status.value,
    }
