from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import uuid

from app.database import get_db
from app.models.driver import Driver, DriverStatusEnum
from app.models.user import User, RoleEnum
from app.models.vehicle import Vehicle
from app.schemas.driver import CreateDriverRequest, UpdateDriverRequest, DriverResponse
from app.dependencies import require_roles

router = APIRouter(prefix="/drivers", tags=["Drivers"])


@router.post("/", response_model=DriverResponse, status_code=status.HTTP_201_CREATED)
def create_driver(
    data: CreateDriverRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("MANAGER")),
):
    """
    Creează profil de șofer pentru un user SOFER din compania ta.
    
    Fluxul complet:
    1. MANAGER invită un SOFER prin /admin/users/invite (se creează contul)
    2. MANAGER creează profilul de driver aici (se alocă vehicul, program)
    3. Acum șoferul poate primi curse
    """
    # Verifică că user-ul există și e SOFER din aceeași companie
    user = db.query(User).filter(User.id == data.user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="User inexistent")

    if user.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="User-ul nu e din compania ta")

    user_role = user.role.value if hasattr(user.role, 'value') else str(user.role)
    if user_role != "SOFER":
        raise HTTPException(
            status_code=400,
            detail=f"User-ul are rolul {user_role}, nu SOFER",
        )

    # Verifică să nu aibă deja profil de driver
    existing = db.query(Driver).filter(Driver.user_id == data.user_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Acest user are deja profil de șofer")

    # Dacă a specificat vehicul, verifică să fie din aceeași companie
    if data.vehicle_id:
        vehicle = db.query(Vehicle).filter(
            Vehicle.id == data.vehicle_id,
            Vehicle.company_id == current_user.company_id,
        ).first()
        if not vehicle:
            raise HTTPException(status_code=404, detail="Vehicul inexistent în compania ta")

    new_driver = Driver(
        company_id=current_user.company_id,
        user_id=data.user_id,
        vehicle_id=data.vehicle_id,
        shift_start=data.shift_start,
        shift_end=data.shift_end,
        max_hours_day=data.max_hours_day,
        hours_driven_today=0.0,
        status=DriverStatusEnum.AVAILABLE,
    )

    db.add(new_driver)
    db.commit()
    db.refresh(new_driver)

    return new_driver


@router.get("/", response_model=list[DriverResponse])
def list_drivers(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("MANAGER", "DISPECER")),
):
    """Listează toți șoferii din compania ta."""
    drivers = db.query(Driver).filter(
        Driver.company_id == current_user.company_id
    ).all()
    return drivers


@router.get("/{driver_id}", response_model=DriverResponse)
def get_driver(
    driver_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("MANAGER", "DISPECER")),
):
    """Returnează un șofer specific din compania ta."""
    driver = db.query(Driver).filter(
        Driver.id == driver_id,
        Driver.company_id == current_user.company_id,
    ).first()

    if not driver:
        raise HTTPException(status_code=404, detail="Șofer inexistent")

    return driver


@router.patch("/{driver_id}", response_model=DriverResponse)
def update_driver(
    driver_id: uuid.UUID,
    data: UpdateDriverRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("MANAGER")),
):
    """Actualizează profilul unui șofer (vehicul, program, status)."""
    driver = db.query(Driver).filter(
        Driver.id == driver_id,
        Driver.company_id == current_user.company_id,
    ).first()

    if not driver:
        raise HTTPException(status_code=404, detail="Șofer inexistent")

    update_data = data.model_dump(exclude_unset=True)

    if "status" in update_data:
        update_data["status"] = DriverStatusEnum(update_data["status"])

    # Dacă schimbă vehiculul, verifică să fie din compania ta
    if "vehicle_id" in update_data and update_data["vehicle_id"]:
        vehicle = db.query(Vehicle).filter(
            Vehicle.id == update_data["vehicle_id"],
            Vehicle.company_id == current_user.company_id,
        ).first()
        if not vehicle:
            raise HTTPException(status_code=404, detail="Vehicul inexistent în compania ta")

    for field, value in update_data.items():
        setattr(driver, field, value)

    db.commit()
    db.refresh(driver)

    return driver