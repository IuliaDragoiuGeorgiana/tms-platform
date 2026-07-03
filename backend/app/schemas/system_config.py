from pydantic import BaseModel, field_validator


class ServiceTimeConfigResponse(BaseModel):
    standard_pickup_service_min: int
    standard_delivery_service_min: int

    fragil_pickup_service_min: int
    fragil_delivery_service_min: int

    perisabil_pickup_service_min: int
    perisabil_delivery_service_min: int

    adr_pickup_service_min: int
    adr_delivery_service_min: int

    service_extra_minutes_per_500kg: int
    service_extra_minutes_per_5m3: int
    service_max_minutes: int


class UpdateServiceTimeConfigRequest(BaseModel):
    standard_pickup_service_min: int
    standard_delivery_service_min: int

    fragil_pickup_service_min: int
    fragil_delivery_service_min: int

    perisabil_pickup_service_min: int
    perisabil_delivery_service_min: int

    adr_pickup_service_min: int
    adr_delivery_service_min: int

    service_extra_minutes_per_500kg: int
    service_extra_minutes_per_5m3: int
    service_max_minutes: int

    @field_validator("*")
    @classmethod
    def positive_values(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Valorile de configurare trebuie să fie pozitive")

        if value > 240:
            raise ValueError("Valorile de configurare nu pot depăși 240 minute")

        return value

class CostConfigResponse(BaseModel):
    fuel_price_per_liter: float
    driver_hourly_rate: float
    vehicle_daily_amortization: float
    vehicle_consumption_van: float
    vehicle_consumption_truck: float
    vehicle_consumption_car: float


class UpdateCostConfigRequest(CostConfigResponse):
    @field_validator("*")
    @classmethod
    def positive_values(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("Valorile de cost trebuie să fie pozitive")
        return value
