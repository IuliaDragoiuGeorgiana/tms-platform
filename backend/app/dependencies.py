from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.config import SECRET_KEY, ALGORITHM
from app.models.user import User
from typing import List

# Spune FastAPI că tokenul vine în header-ul Authorization: Bearer <token>
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Extrage JWT din header, decodifică, găsește user-ul în DB.
    Dacă tokenul e invalid sau user-ul nu există → 401.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalid sau expirat",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()

    if user is None or not user.is_active:
        raise credentials_exception

    return user

def require_roles(*allowed_roles: str):
    """
    Dependency factory — returnează o funcție care verifică dacă user-ul curent 
    are unul din rolurile permise.
    
    Utilizare: current_user: User = Depends(require_roles("SUPER_ADMIN", "MANAGER"))
    """
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        user_role = current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role)
        if user_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Acest endpoint necesită unul din rolurile: {', '.join(allowed_roles)}",
            )
        return current_user
    return role_checker