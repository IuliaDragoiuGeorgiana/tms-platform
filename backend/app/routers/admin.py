from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import uuid

from app.database import get_db
from app.models.user import User, RoleEnum
from app.schemas.auth import InviteUserRequest, UserResponse
from app.core.security import hash_password, generate_temporary_password
from app.dependencies import require_roles

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

    elif current_role == "MANAGER":
        if data.role not in ("DISPECER", "SOFER"):
            raise HTTPException(
                status_code=400,
                detail="MANAGER poate invita doar DISPECER sau SOFER",
            )
        # Ignorăm company_id din request — MANAGER poate invita doar în compania lui
        target_company_id = current_user.company_id

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

    # TODO: trimite email cu parola temporară
    # Momentan returnăm parola în response pentru testare în Swagger
    return {
        "message": "Cont creat cu succes",
        "user_id": str(new_user.id),
        "email": new_user.email,
        "temporary_password": temp_password,
        "note": "În producție această parolă se va trimite pe email, nu în response",
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