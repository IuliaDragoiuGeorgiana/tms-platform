from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.company import Company
from app.models.user import User, RoleEnum
from app.schemas.auth import (
    RegisterRequest,
    TokenResponse,
    UserResponse,
    ChangePasswordRequest,
)
from app.core.security import hash_password, verify_password, create_access_token
from app.dependencies import get_current_user

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    """
    Self-registration — doar pentru CLIENT.
    
    Cum funcționează:
    1. Clientul accesează tms.ro/register/transport-rapid
    2. Frontend-ul citește "transport-rapid" din URL
    3. Frontend-ul trimite { email, password, full_name, company_slug: "transport-rapid" }
    4. Backend-ul caută compania cu slug-ul respectiv
    5. Creează contul CLIENT asociat acelei companii
    6. Contul e neaprobat (is_approved=False) până când MANAGER-ul companiei aprobă
    """
    # Pas 1: Caută compania după slug
    company = db.query(Company).filter(Company.slug == data.company_slug).first()

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Nu există nicio companie cu codul '{data.company_slug}'",
        )

    # Pas 2: Verifică dacă compania e activă
    if not company.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Această companie nu mai este activă pe platformă",
        )

    # Pas 3: Verifică email duplicat
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email-ul este deja înregistrat",
        )

    # Pas 4: Creează user-ul CLIENT
    new_user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        role=RoleEnum.CLIENT,
        company_id=company.id,       # asociat automat cu compania din slug
        is_active=True,
        is_approved=False,           # MANAGER-ul companiei trebuie să aprobe
        must_change_password=False,  # și-a setat singur parola
        phone=data.phone,
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return new_user


@router.post("/login", response_model=TokenResponse)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """
    Login compatibil cu Swagger OAuth2.
    În câmpul 'username' din Swagger se introduce email-ul.
    """
    user = db.query(User).filter(User.email == form_data.username).first()

    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email sau parolă incorectă",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Contul este dezactivat",
        )

    if not user.is_approved:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Contul așteaptă aprobare de la administrator",
        )

    token = create_access_token({
        "sub": str(user.id),
        "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        "company_id": str(user.company_id) if user.company_id else None,
    })

    return TokenResponse(
        access_token=token,
        must_change_password=user.must_change_password,
    )


@router.post("/change-password", status_code=status.HTTP_200_OK)
def change_password(
    data: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Schimbă parola user-ului curent.
    Obligatoriu la prima logare pentru user-ii invitați.
    """
    if not verify_password(data.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parola curentă e incorectă",
        )

    if data.current_password == data.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parola nouă trebuie să fie diferită de cea curentă",
        )

    current_user.password_hash = hash_password(data.new_password)
    current_user.must_change_password = False
    db.commit()

    return {"message": "Parolă schimbată cu succes"}


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """Returnează datele user-ului curent."""
    return current_user