from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import uuid

from app.database import get_db
from app.models.user import User, RoleEnum
from app.schemas.auth import InviteUserRequest, UserResponse
from app.core.security import hash_password, generate_temporary_password
from app.dependencies import require_roles
from app.services.email_service import send_temporary_password_email
from app.models.company import Company

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.post(
    "/users/invite",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
)
def invite_user(
    data: InviteUserRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("SUPER_ADMIN", "MANAGER")),
):
    """
    Creează un cont nou cu parolă temporară.
    - SUPER_ADMIN poate crea MANAGER (cu company_id specificat)
    - MANAGER poate crea DISPECER sau SOFER (în compania lui)
    User-ul creat va fi forțat să-și schimbe parola la prima logare.
    """
    current_role = current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role)

    # Validare rol permis pentru a fi invitat
    if current_role == "SUPER_ADMIN":
        if data.role != "MANAGER":
            raise HTTPException(
                status_code=400,
                detail="SUPER_ADMIN poate invita doar MANAGER",
            )
        if not data.company_id:
            raise HTTPException(
                status_code=400,
                detail="SUPER_ADMIN trebuie să specifice company_id",
            )
        target_company_id = data.company_id

        company = db.query(Company).filter(Company.id == target_company_id).first()

        if not company:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Compania nu a fost găsită",
            )

        if not company.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Nu poți invita useri într-o companie dezactivată",
            )
        

    elif current_role == "MANAGER":
        if data.role not in ("DISPECER", "SOFER"):
            raise HTTPException(
                status_code=400,
                detail="MANAGER poate invita doar DISPECER sau SOFER",
            )
        # Ignorăm company_id din request — MANAGER poate invita doar în compania lui
        target_company_id = current_user.company_id
        if not target_company_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Managerul nu este asociat unei companii",
            )

    # Verifică email duplicat
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email-ul este deja folosit")

    # Generează parolă temporară
    temp_password = generate_temporary_password()

    # Creează user
    new_user = User(
        email=data.email,
        password_hash=hash_password(temp_password),
        full_name=data.full_name,
        role=RoleEnum(data.role),
        company_id=target_company_id,
        is_active=True,
        is_approved=True,       # invitat de admin → automat aprobat
        must_change_password=True,  # forțat să schimbe parola
        invited_by_id=current_user.id,
        phone=data.phone,
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    email_sent = send_temporary_password_email(
        to_email=new_user.email,
        to_name=new_user.full_name,
        temporary_password=temp_password,
    )

    return {
        "message": "Cont creat cu succes. Parola temporară a fost trimisă pe email.",
        "user_id": str(new_user.id),
        "email": new_user.email,
        "role": new_user.role.value if hasattr(new_user.role, "value") else str(new_user.role),
        "must_change_password": new_user.must_change_password,
        "email_sent": email_sent,
    }


@router.patch("/users/{user_id}/approve", response_model=UserResponse)
def approve_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("MANAGER", "SUPER_ADMIN")),
):
    """
    Aprobă un CLIENT care s-a auto-înregistrat.
    MANAGER aprobă doar clienți din compania lui.
    """
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="User inexistent")

    current_role = current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role)

    target_role = user.role.value if hasattr(user.role, "value") else str(user.role)

    if target_role != "CLIENT":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Doar conturile de CLIENT se aprobă prin acest endpoint",
        )

    # MANAGER aprobă doar în compania lui
    if current_role == "MANAGER" and user.company_id != current_user.company_id:
        raise HTTPException(
            status_code=403,
            detail="Nu poți aproba useri din alte companii",
        )

    if user.is_approved:
        raise HTTPException(status_code=400, detail="User-ul e deja aprobat")

    user.is_approved = True
    db.commit()
    db.refresh(user)

    return user

@router.patch("/users/{user_id}/activate", response_model=UserResponse)
def activate_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("SUPER_ADMIN", "MANAGER")),
):
    """
    Activează un utilizator.

    SUPER_ADMIN poate activa MANAGERI.
    MANAGER poate activa CLIENT, DISPECER sau SOFER din propria companie.
    """
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User inexistent",
        )

    current_role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    target_role = user.role.value if hasattr(user.role, "value") else str(user.role)

    if current_role == "SUPER_ADMIN":
        if target_role != "MANAGER":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="SUPER_ADMIN poate activa doar MANAGERI",
            )

    elif current_role == "MANAGER":
        if user.company_id != current_user.company_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Nu poți activa useri din alte companii",
            )

        if target_role not in ("CLIENT", "DISPECER", "SOFER"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="MANAGER poate activa doar CLIENT, DISPECER sau SOFER",
            )

    if user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User-ul este deja activ",
        )

    user.is_active = True
    db.commit()
    db.refresh(user)

    return user


@router.patch("/users/{user_id}/deactivate", response_model=UserResponse)
def deactivate_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("SUPER_ADMIN", "MANAGER")),
):
    """
    Dezactivează un utilizator.

    SUPER_ADMIN poate dezactiva MANAGERI.
    MANAGER poate dezactiva CLIENT, DISPECER sau SOFER din propria companie.
    """
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User inexistent",
        )

    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nu îți poți dezactiva propriul cont",
        )

    current_role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    target_role = user.role.value if hasattr(user.role, "value") else str(user.role)

    if current_role == "SUPER_ADMIN":
        if target_role != "MANAGER":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="SUPER_ADMIN poate dezactiva doar MANAGERI",
            )

    elif current_role == "MANAGER":
        if user.company_id != current_user.company_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Nu poți dezactiva useri din alte companii",
            )

        if target_role not in ("CLIENT", "DISPECER", "SOFER"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="MANAGER poate dezactiva doar CLIENT, DISPECER sau SOFER",
            )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User-ul este deja dezactivat",
        )

    user.is_active = False
    db.commit()
    db.refresh(user)

    return user

@router.get("/users/employees", response_model=list[UserResponse])
def list_company_employees(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("MANAGER")),
):
    """
    Listează dispecerii și șoferii din compania managerului curent.
    """
    employees = (
        db.query(User)
        .filter(
            User.company_id == current_user.company_id,
            User.role.in_([RoleEnum.DISPECER, RoleEnum.SOFER]),
        )
        .order_by(User.full_name.asc())
        .all()
    )

    return employees

@router.get("/clients", response_model=list[UserResponse])
def list_company_clients(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("SUPER_ADMIN", "MANAGER", "DISPECER")),
):
    """
    Listează clienții.
    SUPER_ADMIN vede toți clienții, iar MANAGER/DISPECER doar clienții companiei curente.
    """
    query = db.query(User).filter(
        User.role == RoleEnum.CLIENT,
    )

    current_role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)

    if current_role != "SUPER_ADMIN":
        query = query.filter(User.company_id == current_user.company_id)

    return query.order_by(User.full_name.asc()).all()
