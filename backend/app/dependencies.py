from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.company import Company
from app.core.config import SECRET_KEY, ALGORITHM


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Extrage user-ul curent din JWT token.
    Verifică:
    - token valid
    - user existent și activ
    - companie activă pentru userii non-SUPER_ADMIN
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Nu s-a putut valida token-ul",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str | None = payload.get("sub")

        if user_id is None:
            raise credentials_exception

    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()

    if user is None or not user.is_active:
        raise credentials_exception

    current_role = (
        user.role.value
        if hasattr(user.role, "value")
        else str(user.role)
    )

    # SUPER_ADMIN nu aparține unei companii, deci nu verificăm company_id.
    if current_role != "SUPER_ADMIN":
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

    return user


def require_roles(*allowed_roles: str):
    """
    Factory pentru dependency care verifică rolul user-ului.
    Exemplu: require_roles("MANAGER", "DISPECER")
    """

    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        current_role = (
            current_user.role.value
            if hasattr(current_user.role, "value")
            else str(current_user.role)
        )

        if current_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Acces interzis. Roluri permise: {', '.join(allowed_roles)}",
            )

        return current_user

    return role_checker