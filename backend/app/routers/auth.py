from datetime import datetime, timezone

from app.core.security import (
    create_access_token,
    create_reset_token_expiry,
    generate_reset_token,
    hash_password,
    hash_reset_token,
    verify_password,
)
from app.database import get_db
from app.dependencies import get_current_user
from app.models.company import Company
from app.models.password_reset_token import PasswordResetToken
from app.models.user import RoleEnum, User
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserResponse,
)
from app.services.email_service import send_password_reset_email
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
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
        company_id=company.id,  # asociat automat cu compania din slug
        is_active=True,
        is_approved=False,  # MANAGER-ul companiei trebuie să aprobe
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

    user_role = user.role.value if hasattr(user.role, "value") else str(user.role)

    if user_role != "SUPER_ADMIN":
        if not user.company_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Utilizatorul nu este asociat unei companii",
            )

        company = db.query(Company).filter(Company.id == user.company_id).first()

        if not company or not company.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Compania ta a fost dezactivată. Contactează administratorul platformei.",
            )

    token = create_access_token(
        {
            "sub": str(user.id),
            "role": user_role,
            "company_id": str(user.company_id) if user.company_id else None,
        }
    )
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


@router.post("/forgot-password", response_model=dict)
def forgot_password(
    data: ForgotPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Inițiază resetarea parolei.

    Răspunsul este generic pentru a nu dezvălui dacă emailul există în sistem.
    Dacă userul există și este activ, sistemul generează un token temporar,
    salvează doar hash-ul în DB și trimite tokenul real pe email.
    """
    user = db.query(User).filter(User.email == data.email).first()

    if user and user.is_active:
        # Invalidăm tokenurile vechi nefolosite ale userului.
        db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        ).delete()

        reset_token = generate_reset_token()

        print(reset_token)

        token_record = PasswordResetToken(
            user_id=user.id,
            token_hash=hash_reset_token(reset_token),
            expires_at=create_reset_token_expiry(),
            ip_address=request.client.host if request.client else None,
            user_agent=(request.headers.get("user-agent") or "")[:255],
        )

        db.add(token_record)
        db.commit()

        send_password_reset_email(
            to_email=user.email,
            to_name=user.full_name or user.email,
            reset_token=reset_token,
        )

    return {
        "message": "Dacă adresa de email există în sistem, vei primi un link de resetare parolă în câteva momente."
    }


@router.post("/reset-password", response_model=dict)
def reset_password(
    data: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    """
    Setează o parolă nouă folosind tokenul primit pe email.

    Tokenul este de unică folosință. După resetare, este marcat ca folosit,
    iar celelalte tokenuri active ale userului sunt invalidate.
    """
    token_hash = hash_reset_token(data.token)

    token_record = (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at.is_(None),
        )
        .first()
    )

    if not token_record:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token invalid sau deja folosit",
        )

    if token_record.is_expired():
        db.delete(token_record)
        db.commit()

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tokenul a expirat. Solicită un nou link de resetare.",
        )

    user = db.query(User).filter(User.id == token_record.user_id).first()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token invalid sau utilizator inactiv",
        )

    user.password_hash = hash_password(data.new_password)
    user.must_change_password = False

    token_record.used_at = datetime.now(timezone.utc)

    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
        PasswordResetToken.id != token_record.id,
    ).delete()

    db.commit()

    return {
        "message": "Parola a fost schimbată cu succes. Te poți autentifica acum cu noua parolă."
    }


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """Returnează datele user-ului curent."""
    return current_user
