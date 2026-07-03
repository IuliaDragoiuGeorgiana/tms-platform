from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_roles
from app.models.user import User
from app.models.system_config import SystemConfig, ConfigDataTypeEnum
from app.schemas.system_config import (
    CostConfigResponse,
    ServiceTimeConfigResponse,
    UpdateCostConfigRequest,
    UpdateServiceTimeConfigRequest,
)
from app.services.service_time_service import DEFAULT_CONFIG
from app.services.trip_cost_service import DEFAULT_COST_CONFIG, get_cost_config_value


router = APIRouter(prefix="/system-config", tags=["System Config"])


SERVICE_TIME_CONFIG_KEYS = [
    "standard_pickup_service_min",
    "standard_delivery_service_min",
    "fragil_pickup_service_min",
    "fragil_delivery_service_min",
    "perisabil_pickup_service_min",
    "perisabil_delivery_service_min",
    "adr_pickup_service_min",
    "adr_delivery_service_min",
    "service_extra_minutes_per_500kg",
    "service_extra_minutes_per_5m3",
    "service_max_minutes",
]


def get_config_value(db: Session, company_id, key: str) -> int:
    config = (
        db.query(SystemConfig)
        .filter(
            SystemConfig.company_id == company_id,
            SystemConfig.key == key,
        )
        .first()
    )

    if not config:
        return DEFAULT_CONFIG[key]

    try:
        return int(config.value)
    except (TypeError, ValueError):
        return DEFAULT_CONFIG[key]


@router.get("/service-time", response_model=ServiceTimeConfigResponse)
def get_service_time_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("MANAGER")),
):
    """
    Returnează configurația de service time pentru compania Managerului.
    Dacă o cheie nu există în DB, se întoarce valoarea default din cod.
    """
    values = {
        key: get_config_value(db, current_user.company_id, key)
        for key in SERVICE_TIME_CONFIG_KEYS
    }

    return ServiceTimeConfigResponse(**values)


@router.put("/service-time", response_model=ServiceTimeConfigResponse)
def update_service_time_config(
    data: UpdateServiceTimeConfigRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("MANAGER")),
):
    """
    Permite Managerului să configureze timpii standard de service
    pentru compania lui.
    """
    payload = data.model_dump()

    for key, value in payload.items():
        config = (
            db.query(SystemConfig)
            .filter(
                SystemConfig.company_id == current_user.company_id,
                SystemConfig.key == key,
            )
            .first()
        )

        if config:
            config.value = str(value)
            config.data_type = ConfigDataTypeEnum.INT
            config.updated_by = current_user.id
        else:
            config = SystemConfig(
                company_id=current_user.company_id,
                key=key,
                value=str(value),
                data_type=ConfigDataTypeEnum.INT,
                description=f"Service time configuration: {key}",
                updated_by=current_user.id,
            )
            db.add(config)

    db.commit()

    values = {
        key: get_config_value(db, current_user.company_id, key)
        for key in SERVICE_TIME_CONFIG_KEYS
    }

    return ServiceTimeConfigResponse(**values)

@router.get("/costs", response_model=CostConfigResponse)
def get_cost_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("MANAGER")),
):
    values = {
        key: float(get_cost_config_value(db, current_user.company_id, key))
        for key in DEFAULT_COST_CONFIG
    }
    return CostConfigResponse(**values)


@router.put("/costs", response_model=CostConfigResponse)
def update_cost_config(
    data: UpdateCostConfigRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("MANAGER")),
):
    for key, value in data.model_dump().items():
        config = (
            db.query(SystemConfig)
            .filter(
                SystemConfig.company_id == current_user.company_id,
                SystemConfig.key == key,
            )
            .first()
        )
        if config:
            config.value = str(value)
            config.data_type = ConfigDataTypeEnum.DECIMAL
            config.updated_by = current_user.id
        else:
            db.add(SystemConfig(
                company_id=current_user.company_id,
                key=key,
                value=str(value),
                data_type=ConfigDataTypeEnum.DECIMAL,
                description=f"Trip cost configuration: {key}",
                updated_by=current_user.id,
            ))
    db.commit()
    values = {
        key: float(get_cost_config_value(db, current_user.company_id, key))
        for key in DEFAULT_COST_CONFIG
    }
    return CostConfigResponse(**values)
