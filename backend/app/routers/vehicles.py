from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import uuid

from app.database import get_db
from app.models.vehicle import Vehicle, VehicleTypeEnum, VehicleStatusEnum, FuelTypeEnum
from app.models.user import User
from app.schemas.vehicle import CreateVehicleRequest, UpdateVehicleRequest, VehicleResponse
from app.dependencies import require_roles

router = APIRouter(prefix="/vehicles", tags=["Vehicles"])


@router.post("/", response_model=VehicleResponse, status_code=status.HTTP_201_CREATED)
def create_vehicle(
    data: CreateVehicleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("MANAGER")),
):
    """
    Adaugă un vehicul nou în flota companiei.
    Doar MANAGER poate face asta.
    company_id se ia automat din tokenul managerului — nu poate adăuga
    vehicule în altă companie.
    """
    # Verifică număr înmatriculare duplicat
    existing = db.query(Vehicle).filter(Vehicle.plate == data.plate).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Vehiculul cu numărul {data.plate} există deja",
        )

    new_vehicle = Vehicle(
        company_id=current_user.company_id,  # automat din token
        plate=data.plate,
        capacity_kg=data.capacity_kg,
        capacity_m3=data.capacity_m3,
        type=VehicleTypeEnum(data.type),
        fuel_type=FuelTypeEnum(data.fuel_type),
        avg_consumption=data.avg_consumption,
        itp_expiry=data.itp_expiry,
        status=VehicleStatusEnum.DISPONIBIL,  # nou = disponibil
    )

    db.add(new_vehicle)
    db.commit()
    db.refresh(new_vehicle)

    return new_vehicle


@router.get("/", response_model=list[VehicleResponse])
def list_vehicles(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("MANAGER", "DISPECER")),
):
    """
    Listează vehiculele din compania utilizatorului curent.
    .filter(Vehicle.company_id == current_user.company_id) = multi-tenancy:
    fiecare companie vede DOAR vehiculele ei.
    """
    vehicles = db.query(Vehicle).filter(
        Vehicle.company_id == current_user.company_id
    ).all()
    return vehicles


@router.get("/{vehicle_id}", response_model=VehicleResponse)
def get_vehicle(
    vehicle_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("MANAGER", "DISPECER")),
):
    """Returnează un vehicul specific. Verifică să fie din compania ta."""
    vehicle = db.query(Vehicle).filter(
        Vehicle.id == vehicle_id,
        Vehicle.company_id == current_user.company_id,
    ).first()

    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicul inexistent")

    return vehicle


@router.patch("/{vehicle_id}", response_model=VehicleResponse)
def update_vehicle(
    vehicle_id: uuid.UUID,
    data: UpdateVehicleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("MANAGER")),
):
    """
    Actualizează un vehicul. Doar câmpurile trimise se schimbă.
    
    model_dump(exclude_unset=True) returnează DOAR câmpurile pe care 
    le-a trimis clientul. Dacă trimite {"status": "AVARIAT"}, 
    returnează {"status": "AVARIAT"} — nu atinge restul câmpurilor.
    """
    vehicle = db.query(Vehicle).filter(
        Vehicle.id == vehicle_id,
        Vehicle.company_id == current_user.company_id,
    ).first()

    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicul inexistent")

    update_data = data.model_dump(exclude_unset=True)

    # Convertește string-urile în enum-uri
    if "type" in update_data:
        update_data["type"] = VehicleTypeEnum(update_data["type"])
    if "status" in update_data:
        update_data["status"] = VehicleStatusEnum(update_data["status"])
    if "fuel_type" in update_data:
        update_data["fuel_type"] = FuelTypeEnum(update_data["fuel_type"])

    for field, value in update_data.items():
        setattr(vehicle, field, value)

    db.commit()
    db.refresh(vehicle)

    return vehicle