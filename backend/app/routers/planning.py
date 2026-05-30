from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import date

from app.database import get_db
from app.models.user import User
from app.dependencies import require_roles
from app.services.planning_service import run_planning

router = APIRouter(prefix="/planning", tags=["Planning"])


@router.post("/generate", status_code=status.HTTP_201_CREATED)
def generate_plan(
    planned_date: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("DISPECER", "MANAGER")),
):
    """
    Generează un plan de livrare pentru o zi specifică.
    
    Pipeline complet:
    1. Ia comenzile PENDING din compania ta
    2. Geocodează adresele care nu au coordonate GPS
    3. Calculează câte curse sunt necesare (K-means clustering)
    4. Optimizează ordinea stopurilor per cursă (OR-Tools VRP)
    5. Calculează ETA per stop
    6. Salvează totul în DB (PlanningSession + Trips + TripStops)
    
    Doar DISPECER și MANAGER pot genera planuri.
    """
    if planned_date < date.today():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nu poți genera un plan pentru o dată din trecut",
        )
    result = run_planning(
        db=db,
        company_id=current_user.company_id,
        planned_date=planned_date,
        created_by_id=current_user.id,
    )

    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"],
        )

    return result