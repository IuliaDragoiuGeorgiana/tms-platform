from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
import uuid

from app.database import get_db
from app.models.company import Company
from app.models.user import User, RoleEnum
from app.models.vehicle import Vehicle
from app.models.order import Order
from app.models.trip import Trip
from app.schemas.company import (
    CreateCompanyRequest,
    UpdateCompanyRequest,
    CompanyResponse,
    PublicCompanyResponse,
    CompanyStatsResponse,
)
from app.dependencies import require_roles

router = APIRouter(prefix="/companies", tags=["Companies"])


@router.post("/", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
def create_company(
    data: CreateCompanyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("SUPER_ADMIN")),
):
    """
    Creează o companie nouă.
    Doar SUPER_ADMIN poate crea companii.
    """
    # Verifică că slug-ul nu există deja
    existing = db.query(Company).filter(Company.slug == data.slug.lower()).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Slug-ul '{data.slug}' este deja folosit",
        )

    new_company = Company(
        name=data.name,
        slug=data.slug.lower(),
        plan=data.plan,
        max_vehicles=data.max_vehicles,
        max_users=data.max_users,
        is_active=True,  # Companiile noi sunt active implicit
    )

    db.add(new_company)
    db.commit()
    db.refresh(new_company)

    return new_company


@router.get("/", response_model=list[CompanyResponse])
def list_companies(
    is_active: bool | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("SUPER_ADMIN")),
):
    """
    Listează toate companiile din platformă.
    Doar SUPER_ADMIN poate vedea lista completă.
    
    Parametru opțional is_active pentru filtrare.
    """
    query = db.query(Company)

    if is_active is not None:
        query = query.filter(Company.is_active == is_active)

    query = query.order_by(Company.created_at.desc())

    return query.all()


@router.get("/public/signup-options", response_model=list[PublicCompanyResponse])
def list_signup_companies(
    db: Session = Depends(get_db),
):
    """
    Listează companiile active pentru formularul public de înregistrare client.
    Expune doar numele și slug-ul necesar pentru signup.
    """
    return (
        db.query(Company)
        .filter(Company.is_active == True)
        .order_by(Company.name.asc())
        .all()
    )


@router.get("/{company_id}", response_model=CompanyResponse)
def get_company(
    company_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("SUPER_ADMIN")),
):
    """Returnează detalii despre o companie specifică."""
    company = db.query(Company).filter(Company.id == company_id).first()

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Compania nu a fost găsită",
        )

    return company


@router.patch("/{company_id}", response_model=CompanyResponse)
def update_company(
    company_id: uuid.UUID,
    data: UpdateCompanyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("SUPER_ADMIN")),
):
    """
    Actualizează o companie.
    Permite schimbarea numelui, statusului (is_active), planului și limitelor.
    """
    company = db.query(Company).filter(Company.id == company_id).first()

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Compania nu a fost găsită",
        )

    # Actualizează doar câmpurile trimise
    update_data = data.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(company, field, value)

    db.commit()
    db.refresh(company)

    return company


@router.patch("/{company_id}/activate", response_model=CompanyResponse)
def activate_company(
    company_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("SUPER_ADMIN")),
):
    """
    Activează o companie dezactivată.
    Userii companiei pot din nou folosi aplicația.
    """
    company = db.query(Company).filter(Company.id == company_id).first()

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Compania nu a fost găsită",
        )

    if company.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Compania este deja activă",
        )

    company.is_active = True
    db.commit()
    db.refresh(company)

    return company


@router.patch("/{company_id}/deactivate", response_model=CompanyResponse)
def deactivate_company(
    company_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("SUPER_ADMIN")),
):
    """
    Dezactivează o companie.
    Toți userii companiei vor pierde accesul la aplicație.
    
    ATENȚIE: Această acțiune blochează imediat toate conturile din companie.
    """
    company = db.query(Company).filter(Company.id == company_id).first()

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Compania nu a fost găsită",
        )

    if not company.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Compania este deja inactivă",
        )

    company.is_active = False
    db.commit()
    db.refresh(company)

    return company


@router.get("/{company_id}/stats", response_model=CompanyStatsResponse)
def get_company_stats(
    company_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("SUPER_ADMIN")),
):
    """
    Returnează statistici despre o companie.
    Util pentru SUPER_ADMIN să monitorizeze utilizarea platformei.
    """
    company = db.query(Company).filter(Company.id == company_id).first()

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Compania nu a fost găsită",
        )

    # Numără utilizatori
    total_users = db.query(func.count(User.id)).filter(User.company_id == company_id).scalar()

    # Numără manageri
    total_managers = (
        db.query(func.count(User.id))
        .filter(
            User.company_id == company_id,
            User.role == RoleEnum.MANAGER,
        )
        .scalar()
    )
    total_dispatchers = (
        db.query(func.count(User.id))
        .filter(
            User.company_id == company_id,
            User.role == RoleEnum.DISPECER,
        )
        .scalar()
    )
    total_drivers = (
        db.query(func.count(User.id))
        .filter(
            User.company_id == company_id,
            User.role == RoleEnum.SOFER,
        )
        .scalar()
    )
    total_clients = (
        db.query(func.count(User.id))
        .filter(
            User.company_id == company_id,
            User.role == RoleEnum.CLIENT,
        )
        .scalar()
    )

    # Numără vehicule
    total_vehicles = db.query(func.count(Vehicle.id)).filter(Vehicle.company_id == company_id).scalar()

    # Numără comenzi
    total_orders = db.query(func.count(Order.id)).filter(Order.company_id == company_id).scalar()

    # Numără curse
    total_trips = db.query(func.count(Trip.id)).filter(Trip.company_id == company_id).scalar()

    return CompanyStatsResponse(
        company_id=company.id,
        company_name=company.name,
        is_active=company.is_active,
        total_users=total_users,
        total_managers=total_managers,
        total_dispatchers=total_dispatchers,
        total_drivers=total_drivers,
        total_clients=total_clients,
        total_vehicles=total_vehicles,
        total_orders=total_orders,
        total_trips=total_trips,
        plan=company.plan,
        max_vehicles=company.max_vehicles,
        max_users=company.max_users,
    )
