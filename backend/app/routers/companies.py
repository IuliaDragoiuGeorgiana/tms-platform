from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.company import Company
from app.models.user import User
from app.schemas.company import CreateCompanyRequest, CompanyResponse
from app.dependencies import require_roles

router = APIRouter(prefix="/companies", tags=["Companies"])


@router.post("/", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
def create_company(
    data: CreateCompanyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("SUPER_ADMIN")),
):
    """
    Creează o companie nouă. Doar SUPER_ADMIN poate face asta.

    Explicație:
    - require_roles("SUPER_ADMIN") verifică automat că user-ul logat e SUPER_ADMIN
    - Dacă alt rol încearcă → primește 403 Forbidden
    - Verificăm că slug-ul e unic (două companii nu pot avea același slug)
    """
    # Verifică slug duplicat
    existing = db.query(Company).filter(Company.slug == data.slug).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Slug-ul '{data.slug}' e deja folosit de altă companie",
        )

    # Verifică și nume duplicat (opțional, dar util)
    existing_name = db.query(Company).filter(Company.name == data.name).first()
    if existing_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"O companie cu numele '{data.name}' există deja",
        )

    # Creează compania
    new_company = Company(
        name=data.name,
        slug=data.slug,
        is_active=True,
        plan=data.plan,
        max_vehicles=data.max_vehicles,
        max_users=data.max_users,
    )

    db.add(new_company)
    db.commit()
    db.refresh(new_company)
    # db.refresh() reîncarcă obiectul din DB, ca să aibă id-ul generat de PostgreSQL
    # și created_at populat de server_default=func.now()

    return new_company


@router.get("/", response_model=list[CompanyResponse])
def list_companies(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("SUPER_ADMIN")),
):
    """
    Listează toate companiile. Doar SUPER_ADMIN poate vedea toate companiile.

    list[CompanyResponse] = returnează o listă de companii, fiecare 
    convertită automat prin CompanyResponse.
    """
    companies = db.query(Company).all()
    return companies