from pydantic import BaseModel


class ManagerKpi(BaseModel):
    label: str
    value: str
    detail: str
    tone: str


class ChartPoint(BaseModel):
    label: str
    value: int


class StatusSlice(BaseModel):
    label: str
    value: int
    color: str


class DriverWorkload(BaseModel):
    driver: str
    trips: int
    stops: int


class AttentionItem(BaseModel):
    title: str
    detail: str
    severity: str


class TripSummary(BaseModel):
    id: str
    driver: str
    route: str
    progress: int
    status: str


class ManagerDashboardResponse(BaseModel):
    kpis: list[ManagerKpi]
    orderTrend: list[ChartPoint]
    orderStatus: list[StatusSlice]
    tripStatus: list[ChartPoint]
    fleetStatus: list[ChartPoint]
    driverStatus: list[ChartPoint]
    driverWorkload: list[DriverWorkload]
    attention: list[AttentionItem]
    todayTrips: list[TripSummary]


class SuperAdminKpi(BaseModel):
    label: str
    value: str
    detail: str
    tone: str


class SuperAdminKpiSection(BaseModel):
    title: str
    description: str
    kpis: list[SuperAdminKpi]


class SuperAdminDashboardResponse(BaseModel):
    sections: list[SuperAdminKpiSection]


class DispatcherAttentionItem(BaseModel):
    title: str
    detail: str
    severity: str


class DispatcherDashboardResponse(BaseModel):
    kpis: list[ManagerKpi]
    ongoingTrips: list[TripSummary]
    attention: list[DispatcherAttentionItem]
