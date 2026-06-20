from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_roles
from app.models.company import Company
from app.models.driver import Driver, DriverStatusEnum
from app.models.incident import Incident
from app.models.order import Order, OrderStatusEnum
from app.models.password_reset_token import PasswordResetToken
from app.models.planning_session import PlanningSession, PlanningStatusEnum
from app.models.trip import Trip, TripStatusEnum
from app.models.trip_cost import TripCost
from app.models.trip_stop import StopStatusEnum, StopTypeEnum, TripStop
from app.models.user import RoleEnum, User
from app.models.vehicle import Vehicle, VehicleStatusEnum
from app.schemas.dashboard import (
    AttentionItem,
    ChartPoint,
    DispatcherAttentionItem,
    DispatcherDashboardResponse,
    DriverWorkload,
    ManagerDashboardResponse,
    ManagerKpi,
    StatusSlice,
    SuperAdminDashboardResponse,
    SuperAdminKpi,
    SuperAdminKpiSection,
    TripSummary,
)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


ORDER_STATUS_COLORS = {
    "PENDING": "#f59e0b",
    "PLANNED": "#2563eb",
    "IN_DELIVERY": "#7c3aed",
    "DELIVERED": "#16a34a",
    "FAILED": "#dc2626",
    "CANCELLED": "#64748b",
}


def _enum_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _period_start(period_days: int) -> tuple[date, datetime]:
    today = date.today()
    start_date = today - timedelta(days=period_days - 1)
    return start_date, datetime.combine(start_date, time.min)


def _money(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _count_by_status(items, status_attr: str) -> Counter[str]:
    return Counter(_enum_value(getattr(item, status_attr)) for item in items)


def _format_int(value: int) -> str:
    return f"{value:,}"


def _format_percent(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "0%"

    return f"{round((numerator / denominator) * 100)}%"


def _kpi_tone_for_pending(count: int) -> str:
    if count >= 10:
        return "danger"
    if count > 0:
        return "warn"
    return "good"


def _build_order_trend(orders: list[Order], period_days: int, start_date: date) -> list[ChartPoint]:
    if period_days == 1:
        buckets = [8, 10, 12, 14, 16, 18]
        counts = {hour: 0 for hour in buckets}

        for order in orders:
            created_hour = order.created_at.hour if order.created_at else 0
            bucket = max((hour for hour in buckets if created_hour >= hour), default=buckets[0])
            counts[bucket] += 1

        return [ChartPoint(label=f"{hour:02d}:00", value=counts[hour]) for hour in buckets]

    if period_days == 7:
        labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        counts = defaultdict(int)

        for order in orders:
            if order.created_at:
                counts[order.created_at.date()] += 1

        return [
            ChartPoint(
                label=labels[(start_date + timedelta(days=offset)).weekday()],
                value=counts[start_date + timedelta(days=offset)],
            )
            for offset in range(7)
        ]

    bucket_size = 8
    points: list[ChartPoint] = []

    for index in range(4):
        bucket_start = start_date + timedelta(days=index * bucket_size)
        bucket_end = bucket_start + timedelta(days=bucket_size - 1)
        value = sum(
            1
            for order in orders
            if order.created_at and bucket_start <= order.created_at.date() <= bucket_end
        )
        points.append(ChartPoint(label=f"W{index + 1}", value=value))

    return points


def _success_rate(order_status_counts: Counter[str]) -> tuple[int, int, int]:
    delivered = order_status_counts.get("DELIVERED", 0)
    failed = order_status_counts.get("FAILED", 0)
    cancelled = order_status_counts.get("CANCELLED", 0)
    resolved = delivered + failed + cancelled
    success_rate = round((delivered / resolved) * 100) if resolved else 0
    return success_rate, delivered, failed


def _build_attention(
    unresolved_incidents: int,
    major_incidents: int,
    failed_orders: int,
    interrupted_trips: int,
    unavailable_vehicles: int,
    cost_variance_percent: float,
) -> list[AttentionItem]:
    items: list[AttentionItem] = []

    if major_incidents:
        items.append(
            AttentionItem(
                title=f"{major_incidents} unresolved major incidents",
                detail="Major incidents remain open and need manager review.",
                severity="High",
            )
        )
    elif unresolved_incidents:
        items.append(
            AttentionItem(
                title=f"{unresolved_incidents} unresolved incidents",
                detail="Operational incidents are waiting for resolution.",
                severity="Medium",
            )
        )

    if failed_orders:
        items.append(
            AttentionItem(
                title=f"{failed_orders} failed orders",
                detail="Review failed deliveries and contact affected clients.",
                severity="Medium",
            )
        )

    if interrupted_trips:
        items.append(
            AttentionItem(
                title=f"{interrupted_trips} interrupted trips",
                detail="Recovery trips or replanning may be required.",
                severity="High",
            )
        )

    if unavailable_vehicles:
        items.append(
            AttentionItem(
                title=f"{unavailable_vehicles} unavailable vehicles",
                detail="Vehicles in service or damaged reduce route capacity.",
                severity="Medium",
            )
        )

    if cost_variance_percent > 5:
        items.append(
            AttentionItem(
                title=f"Cost variance +{cost_variance_percent:.1f}%",
                detail="Actual trip costs are above planned cost.",
                severity="Medium",
            )
        )

    return items[:4]


def _trip_route(trip: Trip) -> str:
    pickup = next((stop for stop in trip.stops if stop.stop_type == StopTypeEnum.PICKUP), None)
    delivery = next(
        (stop for stop in reversed(trip.stops) if stop.stop_type == StopTypeEnum.DELIVERY),
        None,
    )

    pickup_city = pickup.order.pickup_city if pickup and pickup.order else None
    delivery_city = delivery.order.delivery_city if delivery and delivery.order else None

    if pickup_city and delivery_city:
        return f"{pickup_city} -> {delivery_city}"

    return "Route pending"


def _trip_progress(trip: Trip) -> int:
    if not trip.stops:
        return 0

    completed = sum(1 for stop in trip.stops if stop.status == StopStatusEnum.COMPLETED)
    return round((completed / len(trip.stops)) * 100)


def _dispatcher_attention_item(
    items: list[DispatcherAttentionItem],
    count: int,
    title: str,
    detail: str,
    severity: str,
) -> None:
    if count <= 0:
        return

    items.append(
        DispatcherAttentionItem(
            title=f"{count} {title}",
            detail=detail,
            severity=severity,
        )
    )


@router.get("/dispatcher", response_model=DispatcherDashboardResponse)
def get_dispatcher_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("DISPECER")),
):
    today = date.today()
    company_id = current_user.company_id

    orders = db.query(Order).filter(Order.company_id == company_id).all()
    trips = db.query(Trip).filter(Trip.company_id == company_id).all()
    drivers = db.query(Driver).filter(Driver.company_id == company_id).all()
    vehicles = db.query(Vehicle).filter(Vehicle.company_id == company_id).all()
    incidents = (
        db.query(Incident)
        .join(Trip, Incident.trip_id == Trip.id)
        .filter(Trip.company_id == company_id)
        .all()
    )
    failed_stops = (
        db.query(TripStop)
        .join(Trip, TripStop.trip_id == Trip.id)
        .filter(
            Trip.company_id == company_id,
            TripStop.status.in_([StopStatusEnum.FAILED, StopStatusEnum.SKIPPED]),
        )
        .all()
    )
    planning_sessions = (
        db.query(PlanningSession)
        .filter(
            PlanningSession.company_id == company_id,
            PlanningSession.status.in_([PlanningStatusEnum.DRAFT, PlanningStatusEnum.PROPOSED]),
        )
        .all()
    )

    orders_to_plan = [
        order
        for order in orders
        if order.status == OrderStatusEnum.PENDING and order.assigned_delivery_date is None
    ]
    ongoing_trips = [trip for trip in trips if trip.status == TripStatusEnum.IN_PROGRESS]
    unassigned_trips = [
        trip
        for trip in trips
        if trip.status in [TripStatusEnum.PROPOSED, TripStatusEnum.APPROVED]
        and (trip.driver_id is None or trip.vehicle_id is None)
    ]
    interrupted_trips = [trip for trip in trips if trip.status == TripStatusEnum.INTERRUPTED]
    problematic_orders = [order for order in orders if order.is_problematic]
    failed_orders = [order for order in orders if order.status == OrderStatusEnum.FAILED]
    overdue_pending_orders = [
        order
        for order in orders
        if order.status in [OrderStatusEnum.PENDING, OrderStatusEnum.PLANNED]
        and order.delivery_deadline < today
    ]
    open_incidents = [incident for incident in incidents if not incident.resolved_at]
    major_incidents = [
        incident
        for incident in open_incidents
        if _enum_value(incident.type) == "MAJOR"
    ]
    available_drivers = sum(1 for driver in drivers if driver.status == DriverStatusEnum.AVAILABLE)
    available_vehicles = sum(1 for vehicle in vehicles if vehicle.status == VehicleStatusEnum.DISPONIBIL)

    attention: list[DispatcherAttentionItem] = []
    _dispatcher_attention_item(
        attention,
        len(major_incidents),
        "major incidents",
        "Open major incidents require dispatcher follow-up.",
        "High",
    )
    _dispatcher_attention_item(
        attention,
        len(interrupted_trips),
        "interrupted trips",
        "Interrupted trips may need recovery planning.",
        "High",
    )
    _dispatcher_attention_item(
        attention,
        len(overdue_pending_orders),
        "overdue pending orders",
        "Orders are past their delivery deadline and are not delivered.",
        "High",
    )
    _dispatcher_attention_item(
        attention,
        len(unassigned_trips),
        "trips missing driver or vehicle",
        "Trips cannot be executed until driver and vehicle are assigned.",
        "Medium",
    )
    _dispatcher_attention_item(
        attention,
        len(problematic_orders),
        "problematic orders",
        "Orders were marked problematic and need review before planning.",
        "Medium",
    )
    _dispatcher_attention_item(
        attention,
        len(failed_orders),
        "failed orders",
        "Failed orders may require client contact or replanning.",
        "Medium",
    )
    _dispatcher_attention_item(
        attention,
        len(failed_stops),
        "failed or skipped stops",
        "Trip stops failed or were skipped during execution.",
        "Medium",
    )
    _dispatcher_attention_item(
        attention,
        len(open_incidents) - len(major_incidents),
        "minor incidents",
        "Open minor incidents are waiting for resolution.",
        "Low",
    )

    attention_count = sum(
        [
            len(major_incidents),
            len(interrupted_trips),
            len(overdue_pending_orders),
            len(unassigned_trips),
            len(problematic_orders),
            len(failed_orders),
            len(failed_stops),
            max(len(open_incidents) - len(major_incidents), 0),
        ]
    )

    return DispatcherDashboardResponse(
        kpis=[
            ManagerKpi(
                label="Ongoing trips",
                value=_format_int(len(ongoing_trips)),
                detail=f"{_format_int(sum(len(trip.stops) for trip in ongoing_trips))} stops in execution",
                tone="neutral",
            ),
            ManagerKpi(
                label="Orders to be planned",
                value=_format_int(len(orders_to_plan)),
                detail="Pending orders without assigned delivery date",
                tone=_kpi_tone_for_pending(len(orders_to_plan)),
            ),
            ManagerKpi(
                label="Need attention",
                value=_format_int(attention_count),
                detail="Orders, trips, stops, and incidents",
                tone="danger" if major_incidents or interrupted_trips else "warn" if attention_count else "good",
            ),
            ManagerKpi(
                label="Unassigned trips",
                value=_format_int(len(unassigned_trips)),
                detail="Missing driver or vehicle",
                tone=_kpi_tone_for_pending(len(unassigned_trips)),
            ),
            ManagerKpi(
                label="Available drivers",
                value=_format_int(available_drivers),
                detail=f"{_format_int(len(drivers))} total drivers",
                tone="good" if available_drivers else "warn",
            ),
            ManagerKpi(
                label="Available vehicles",
                value=_format_int(available_vehicles),
                detail=f"{_format_int(len(vehicles))} total vehicles",
                tone="good" if available_vehicles else "warn",
            ),
            ManagerKpi(
                label="Planning sessions",
                value=_format_int(len(planning_sessions)),
                detail="Draft or proposed plans",
                tone="neutral" if planning_sessions else "good",
            ),
        ],
        ongoingTrips=[
            TripSummary(
                id=f"TRP-{str(trip.id)[:8]}",
                driver=trip.driver_name or "Unassigned",
                route=_trip_route(trip),
                progress=_trip_progress(trip),
                status=_enum_value(trip.status).replace("_", " ").title(),
            )
            for trip in sorted(ongoing_trips, key=lambda item: item.planned_date)[:6]
        ],
        attention=attention[:8],
    )


@router.get("/manager", response_model=ManagerDashboardResponse)
def get_manager_dashboard(
    period: int = Query(7, ge=1, le=30),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("MANAGER")),
):
    period_days = 1 if period <= 1 else 7 if period <= 7 else 30
    start_date, start_datetime = _period_start(period_days)
    today = date.today()
    company_id = current_user.company_id

    orders = (
        db.query(Order)
        .filter(Order.company_id == company_id, Order.created_at >= start_datetime)
        .all()
    )
    trips = (
        db.query(Trip)
        .filter(
            Trip.company_id == company_id,
            Trip.planned_date >= start_date,
            Trip.planned_date <= today,
        )
        .all()
    )
    vehicles = db.query(Vehicle).filter(Vehicle.company_id == company_id).all()
    drivers = db.query(Driver).filter(Driver.company_id == company_id).all()
    incidents = (
        db.query(Incident)
        .join(Trip, Incident.trip_id == Trip.id)
        .filter(Trip.company_id == company_id, Incident.created_at >= start_datetime)
        .all()
    )
    costs = (
        db.query(TripCost)
        .join(Trip, TripCost.trip_id == Trip.id)
        .filter(
            Trip.company_id == company_id,
            Trip.planned_date >= start_date,
            Trip.planned_date <= today,
        )
        .all()
    )

    order_status_counts = _count_by_status(orders, "status")
    trip_status_counts = _count_by_status(trips, "status")
    vehicle_status_counts = _count_by_status(vehicles, "status")
    driver_status_counts = _count_by_status(drivers, "status")

    success_rate, delivered_orders, failed_orders = _success_rate(order_status_counts)
    active_trips = trip_status_counts.get("APPROVED", 0) + trip_status_counts.get("IN_PROGRESS", 0)
    unresolved_incidents = sum(1 for incident in incidents if not incident.resolved_at)
    major_incidents = sum(
        1
        for incident in incidents
        if not incident.resolved_at and _enum_value(incident.type) == "MAJOR"
    )

    planned_cost = sum(_money(cost.total_planned) for cost in costs)
    actual_cost = sum(_money(cost.total_actual) for cost in costs)
    cost_variance_percent = ((actual_cost - planned_cost) / planned_cost * 100) if planned_cost else 0
    available_vehicles = vehicle_status_counts.get("DISPONIBIL", 0)
    unavailable_vehicles = vehicle_status_counts.get("SERVICE", 0) + vehicle_status_counts.get("AVARIAT", 0)
    fleet_availability = round((available_vehicles / len(vehicles)) * 100) if vehicles else 0

    driver_workload: list[DriverWorkload] = []
    for driver in drivers:
        driver_trips = [trip for trip in trips if trip.driver_id == driver.id]
        stops = sum(len(trip.stops) for trip in driver_trips)
        if driver_trips or stops:
            driver_workload.append(
                DriverWorkload(
                    driver=driver.user.full_name if driver.user else "Unknown driver",
                    trips=len(driver_trips),
                    stops=stops,
                )
            )
    driver_workload.sort(key=lambda item: (item.trips, item.stops), reverse=True)

    today_trips = [
        TripSummary(
            id=f"TRP-{str(trip.id)[:8]}",
            driver=trip.driver_name or "Unassigned",
            route=_trip_route(trip),
            progress=_trip_progress(trip),
            status=_enum_value(trip.status).replace("_", " ").title(),
        )
        for trip in sorted(trips, key=lambda item: item.planned_date, reverse=True)[:5]
    ]

    return ManagerDashboardResponse(
        kpis=[
            ManagerKpi(
                label="Orders",
                value=str(len(orders)),
                detail=f"{delivered_orders} delivered, {failed_orders} failed",
                tone="good" if success_rate >= 90 else "warn",
            ),
            ManagerKpi(
                label="Delivery success",
                value=f"{success_rate}%",
                detail=f"{delivered_orders} delivered, {failed_orders} failed",
                tone="good" if success_rate >= 90 else "warn",
            ),
            ManagerKpi(
                label="Active trips",
                value=str(active_trips),
                detail=f"{trip_status_counts.get('COMPLETED', 0)} completed",
                tone="neutral",
            ),
            ManagerKpi(
                label="Open incidents",
                value=str(unresolved_incidents),
                detail=f"{major_incidents} major unresolved",
                tone="danger" if major_incidents else "warn" if unresolved_incidents else "good",
            ),
            ManagerKpi(
                label="Fleet available",
                value=f"{fleet_availability}%",
                detail=f"{available_vehicles} of {len(vehicles)} vehicles",
                tone="good" if fleet_availability >= 70 else "warn",
            ),
        ],
        orderTrend=_build_order_trend(orders, period_days, start_date),
        orderStatus=[
            StatusSlice(
                label=status.replace("_", " ").title(),
                value=order_status_counts.get(status, 0),
                color=ORDER_STATUS_COLORS[status],
            )
            for status in ["PENDING", "PLANNED", "IN_DELIVERY", "DELIVERED", "FAILED", "CANCELLED"]
        ],
        tripStatus=[
            ChartPoint(label=status.value.replace("_", " ").title(), value=trip_status_counts.get(status.value, 0))
            for status in TripStatusEnum
        ],
        fleetStatus=[
            ChartPoint(label=status.value.title(), value=vehicle_status_counts.get(status.value, 0))
            for status in VehicleStatusEnum
        ],
        driverStatus=[
            ChartPoint(label=status.value.replace("_", " ").title(), value=driver_status_counts.get(status.value, 0))
            for status in DriverStatusEnum
        ],
        driverWorkload=driver_workload[:5],
        attention=_build_attention(
            unresolved_incidents=unresolved_incidents,
            major_incidents=major_incidents,
            failed_orders=failed_orders,
            interrupted_trips=trip_status_counts.get("INTERRUPTED", 0),
            unavailable_vehicles=unavailable_vehicles,
            cost_variance_percent=cost_variance_percent,
        ),
        todayTrips=today_trips,
    )


@router.get("/super-admin", response_model=SuperAdminDashboardResponse)
def get_super_admin_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("SUPER_ADMIN")),
):
    _ = current_user
    today = date.today()
    thirty_days_ago = today - timedelta(days=29)
    thirty_days_ago_datetime = datetime.combine(thirty_days_ago, time.min, tzinfo=timezone.utc)

    companies = db.query(Company).all()
    users = db.query(User).all()
    orders = db.query(Order).all()
    recent_orders = [
        order
        for order in orders
        if order.created_at and order.created_at.date() >= thirty_days_ago
    ]
    trips = db.query(Trip).all()
    recent_trips = [
        trip for trip in trips if trip.planned_date and trip.planned_date >= thirty_days_ago
    ]
    vehicles = db.query(Vehicle).all()
    drivers = db.query(Driver).all()
    incidents = db.query(Incident).all()
    recent_reset_tokens = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.created_at >= thirty_days_ago_datetime)
        .all()
    )

    active_companies = sum(1 for company in companies if company.is_active)
    disabled_companies = len(companies) - active_companies
    active_company_ids_all = {company.id for company in companies if company.is_active}
    active_company_ids = {
        order.company_id
        for order in recent_orders
        if order.company_id is not None
    } | {
        trip.company_id
        for trip in recent_trips
        if trip.company_id is not None
    }
    active_company_ids = active_company_ids & active_company_ids_all
    pending_setup = sum(
        1
        for company in companies
        if company.is_active
        and (
            not company.depot_city
            or company.depot_lat is None
            or company.depot_lon is None
            or not any(user.role == RoleEnum.MANAGER for user in company.users)
        )
    )

    managers = sum(1 for user in users if user.role == RoleEnum.MANAGER)
    pending_manager_invites = sum(
        1
        for user in users
        if user.role == RoleEnum.MANAGER and (not user.is_approved or user.must_change_password)
    )
    pending_approvals = sum(1 for user in users if not user.is_approved and user.role != RoleEnum.SUPER_ADMIN)
    inactive_users = sum(1 for user in users if not user.is_active)
    approved_drivers = sum(
        1
        for driver in drivers
        if driver.user and driver.user.is_active and driver.user.is_approved
    )

    order_status_counts = _count_by_status(recent_orders, "status")
    completed_trips = sum(1 for trip in recent_trips if trip.status == TripStatusEnum.COMPLETED)
    vehicles_in_service = sum(1 for vehicle in vehicles if vehicle.status == VehicleStatusEnum.SERVICE)
    unresolved_incidents = sum(1 for incident in incidents if not incident.resolved_at)
    high_priority_incidents = sum(
        1
        for incident in incidents
        if not incident.resolved_at and _enum_value(incident.type) == "MAJOR"
    )
    failed_deliveries = order_status_counts.get("FAILED", 0)
    delivered_orders = order_status_counts.get("DELIVERED", 0)
    failed_delivery_denominator = delivered_orders + failed_deliveries

    return SuperAdminDashboardResponse(
        sections=[
            SuperAdminKpiSection(
                title="Tenant health",
                description="Company activation, setup progress, and platform access.",
                kpis=[
                    SuperAdminKpi(
                        label="Active companies",
                        value=_format_int(active_companies),
                        detail=f"{_format_int(len(companies))} total companies",
                        tone="good" if active_companies else "warn",
                    ),
                    SuperAdminKpi(
                        label="Pending setup",
                        value=_format_int(pending_setup),
                        detail="Missing manager or depot setup",
                        tone=_kpi_tone_for_pending(pending_setup),
                    ),
                    SuperAdminKpi(
                        label="Disabled companies",
                        value=_format_int(disabled_companies),
                        detail="Inactive tenant accounts",
                        tone="danger" if disabled_companies else "good",
                    ),
                    SuperAdminKpi(
                        label="Companies with activity",
                        value=_format_percent(len(active_company_ids), active_companies),
                        detail=f"{_format_int(len(active_company_ids))} active in last 30 days",
                        tone="good" if active_companies and len(active_company_ids) / active_companies >= 0.75 else "warn",
                    ),
                ],
            ),
            SuperAdminKpiSection(
                title="Accounts and approvals",
                description="User governance across all companies.",
                kpis=[
                    SuperAdminKpi(
                        label="Total users",
                        value=_format_int(len(users)),
                        detail="Across all tenants",
                        tone="neutral",
                    ),
                    SuperAdminKpi(
                        label="Managers",
                        value=_format_int(managers),
                        detail=f"{_format_int(pending_manager_invites)} pending invites",
                        tone="neutral" if pending_manager_invites == 0 else "warn",
                    ),
                    SuperAdminKpi(
                        label="Pending approvals",
                        value=_format_int(pending_approvals),
                        detail="Client and employee accounts",
                        tone=_kpi_tone_for_pending(pending_approvals),
                    ),
                    SuperAdminKpi(
                        label="Inactive users",
                        value=_format_int(inactive_users),
                        detail="Deactivated user accounts",
                        tone="neutral" if inactive_users == 0 else "warn",
                    ),
                ],
            ),
            SuperAdminKpiSection(
                title="Platform volume",
                description="Cross-tenant transport activity in the last 30 days.",
                kpis=[
                    SuperAdminKpi(
                        label="Orders this month",
                        value=_format_int(len(recent_orders)),
                        detail="Created in last 30 days",
                        tone="good" if recent_orders else "neutral",
                    ),
                    SuperAdminKpi(
                        label="Trips completed",
                        value=_format_int(completed_trips),
                        detail="Completed in last 30 days",
                        tone="good" if completed_trips else "neutral",
                    ),
                    SuperAdminKpi(
                        label="Vehicles registered",
                        value=_format_int(len(vehicles)),
                        detail=f"{_format_int(vehicles_in_service)} currently in service",
                        tone="neutral",
                    ),
                    SuperAdminKpi(
                        label="Drivers registered",
                        value=_format_int(len(drivers)),
                        detail=f"{_format_int(approved_drivers)} approved",
                        tone="neutral",
                    ),
                ],
            ),
            SuperAdminKpiSection(
                title="Risk and operations",
                description="Issues that need platform-level attention.",
                kpis=[
                    SuperAdminKpi(
                        label="Open incidents",
                        value=_format_int(unresolved_incidents),
                        detail=f"{_format_int(high_priority_incidents)} high priority",
                        tone="danger" if high_priority_incidents else "warn" if unresolved_incidents else "good",
                    ),
                    SuperAdminKpi(
                        label="Failed deliveries",
                        value=_format_percent(failed_deliveries, failed_delivery_denominator),
                        detail=f"{_format_int(failed_deliveries)} failed in last 30 days",
                        tone="warn" if failed_deliveries else "good",
                    ),
                    SuperAdminKpi(
                        label="Password reset requests",
                        value=_format_int(len(recent_reset_tokens)),
                        detail="Requested in last 30 days",
                        tone="neutral",
                    ),
                ],
            ),
        ]
    )
