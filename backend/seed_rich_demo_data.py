"""
Reset and seed a large demo dataset.

This script is intentionally destructive: it removes existing app data before
creating a fresh, populated scenario for local/demo use.

Run from the backend directory:
    python seed_rich_demo_data.py
"""

import hashlib
import random
import secrets
from datetime import date, datetime, time, timedelta, timezone

from app.core.security import hash_password
from app.database import SessionLocal
from app.models.audit_log import AuditLog
from app.models.chat_message import ChatMessage, MessageTypeEnum
from app.models.company import Company, PlanEnum
from app.models.daily_report import DailyReport
from app.models.driver import Driver, DriverStatusEnum
from app.models.incident import Incident, IncidentTypeEnum
from app.models.notification import (
    Notification,
    NotificationChannelEnum,
    NotificationStatusEnum,
)
from app.models.order import (
    MarfaTypeEnum,
    Order,
    OrderSourceEnum,
    OrderStatusEnum,
    PriorityEnum,
    ServiceTimeSourceEnum,
)
from app.models.password_reset_token import PasswordResetToken
from app.models.planning_session import (
    PlanningSession,
    PlanningStatusEnum,
    PlanningStrategyEnum,
)
from app.models.system_config import ConfigDataTypeEnum, SystemConfig
from app.models.trip import Trip, TripStatusEnum
from app.models.trip_cost import TripCost
from app.models.trip_stop import (
    FailureReasonEnum,
    StopStatusEnum,
    StopTypeEnum,
    TripStop,
)
from app.models.user import RoleEnum, User
from app.models.vehicle import FuelTypeEnum, Vehicle, VehicleStatusEnum, VehicleTypeEnum
from app.services.trip_cost_service import upsert_trip_cost
from app.services.planning_service import (
    _build_capacity_by_day_minutes,
    _build_estimated_minutes_by_order,
    _repair_deferred_distribution,
)
from app.services.strategy_service import distribute_orders_by_strategy


PASSWORD = "helloWorld"
TODAY = date.today()


COMPANY_SCENARIOS = [
    {
        "name": "Rapid Curier",
        "slug": "rapid-curier",
        "domain": "rapidcurier.ro",
        "plan": PlanEnum.PRO,
        "depot": ("Cluj", "Cluj-Napoca", "Strada Fabricii", "10", 46.7860, 23.6200),
        "plate_prefix": "RC",
        # One available driver intentionally constrains the comparison to 540
        # estimated minutes per day. Other drivers still populate operational UI.
        "available_drivers": 1,
        "inactive_driver_users": 3,
        "zones": [
            ("Cluj", "Cluj-Napoca", 46.7712, 23.6236),
            ("Cluj", "Floresti", 46.7468, 23.4936),
            ("Bihor", "Oradea", 47.0465, 21.9189),
            ("Alba", "Alba Iulia", 46.0686, 23.5715),
            ("Mures", "Targu Mures", 46.5425, 24.5575),
            ("Sibiu", "Sibiu", 45.7983, 24.1256),
        ],
    },
    {
        "name": "Atlas Freight",
        "slug": "atlas-freight",
        "domain": "atlasfreight.com",
        "plan": PlanEnum.PRO,
        "depot": ("Cluj", "Cluj-Napoca", "Strada Fabricii", "10", 46.7860, 23.6200),
        "plate_prefix": "AF",
        "available_drivers": 1,
        "zones": [
            ("Cluj", "Cluj-Napoca", 46.7712, 23.6236),
            ("Cluj", "Floresti", 46.7468, 23.4936),
            ("Bihor", "Oradea", 47.0465, 21.9189),
            ("Alba", "Alba Iulia", 46.0686, 23.5715),
            ("Mures", "Targu Mures", 46.5425, 24.5575),
            ("Sibiu", "Sibiu", 45.7983, 24.1256),
        ],
    },
    {
        "name": "Cold Chain Logistics",
        "slug": "cold-chain-logistics",
        "domain": "coldchainlogistics.ro",
        "plan": PlanEnum.PRO,
        "depot": ("Cluj", "Cluj-Napoca", "Strada Fabricii", "10", 46.7860, 23.6200),
        "plate_prefix": "CC",
        "available_drivers": 1,
        "zones": [
            ("Cluj", "Cluj-Napoca", 46.7712, 23.6236),
            ("Cluj", "Floresti", 46.7468, 23.4936),
            ("Bihor", "Oradea", 47.0465, 21.9189),
            ("Alba", "Alba Iulia", 46.0686, 23.5715),
            ("Mures", "Targu Mures", 46.5425, 24.5575),
            ("Sibiu", "Sibiu", 45.7983, 24.1256),
        ],
    },
    {
        "name": "Moldova Distribution",
        "slug": "moldova-distribution",
        "domain": "moldovadistribution.ro",
        "plan": PlanEnum.PRO,
        "depot": ("Cluj", "Cluj-Napoca", "Strada Fabricii", "10", 46.7860, 23.6200),
        "plate_prefix": "MD",
        "available_drivers": 1,
        "zones": [
            ("Cluj", "Cluj-Napoca", 46.7712, 23.6236),
            ("Cluj", "Floresti", 46.7468, 23.4936),
            ("Bihor", "Oradea", 47.0465, 21.9189),
            ("Alba", "Alba Iulia", 46.0686, 23.5715),
            ("Mures", "Targu Mures", 46.5425, 24.5575),
            ("Sibiu", "Sibiu", 45.7983, 24.1256),
        ],
    },
]

def dt(day_offset: int, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(
        TODAY + timedelta(days=day_offset),
        time(hour, minute),
        tzinfo=timezone.utc,
    )


def unique_token(seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    return f"demo-{digest}"


def select_vehicle_for_orders(orders: list[Order], vehicles: list[Vehicle], fallback_index: int = 0) -> Vehicle:
    """
    Select the most appropriate vehicle for a set of orders.
    - Finds vehicles that can accommodate all orders
    - Rotates through suitable vehicles to distribute load across fleet
    - Falls back to any available vehicle if no perfect match

    Args:
        orders: List of Order objects to be transported
        vehicles: List of available Vehicle objects to choose from
        fallback_index: Index to use for rotation and fallback

    Returns:
        Selected Vehicle object
    """
    if not vehicles:
        return None

    # Calculate total weight and volume needed
    total_kg = 0.0
    total_m3 = 0.0
    for order in orders:
        kg = float(order.kg) if order.kg else 0.0
        m3 = float(order.m3) if order.m3 else 0.0
        total_kg += kg
        total_m3 += m3

    # Find vehicles that can accommodate these orders
    suitable_vehicles = []
    for vehicle in vehicles:
        cap_kg = float(vehicle.capacity_kg) if vehicle.capacity_kg else 0.0
        cap_m3 = float(vehicle.capacity_m3) if vehicle.capacity_m3 else 0.0

        if cap_kg >= total_kg and cap_m3 >= total_m3:
            suitable_vehicles.append({
                "vehicle": vehicle,
                "capacity_score": cap_kg + cap_m3,  # Prefer smaller vehicles
            })

    if suitable_vehicles:
        # Sort by capacity (smallest suitable first)
        suitable_vehicles.sort(key=lambda x: x["capacity_score"])

        # Use fallback_index to rotate through suitable vehicles
        # This distributes trips across multiple vehicles
        selected_index = fallback_index % len(suitable_vehicles)
        return suitable_vehicles[selected_index]["vehicle"]

    # Fallback: return vehicle by index if no suitable vehicle found
    return vehicles[fallback_index % len(vehicles)]


def cleanup_database(db) -> None:
    delete_order = [
        PasswordResetToken,
        ChatMessage,
        Notification,
        AuditLog,
        DailyReport,
        Incident,
        TripCost,
        TripStop,
        Trip,
        PlanningSession,
        Order,
        SystemConfig,
        Driver,
        Vehicle,
        User,
        Company,
    ]

    for model in delete_order:
        deleted = db.query(model).delete(synchronize_session=False)
        print(f"Deleted {deleted:4d} rows from {model.__tablename__}")

    db.commit()


def create_user(db, email: str, full_name: str, role: RoleEnum, company_id=None, is_active: bool = True) -> User:
    user = User(
        email=email,
        password_hash=hash_password(PASSWORD),
        full_name=full_name,
        role=role,
        company_id=company_id,
        is_active=is_active,
        is_approved=True,
        must_change_password=False,
        phone=f"07{secrets.randbelow(90000000) + 10000000}",
    )
    db.add(user)
    return user


def create_company(db, scenario: dict) -> Company:
    county, city, street, number, lat, lon = scenario["depot"]
    company = Company(
        name=scenario["name"],
        slug=scenario["slug"],
        is_active=True,
        plan=scenario["plan"],
        max_vehicles=80,
        max_users=160,
        settings={
            "auto_assign_driver": True,
            "default_planning_horizon_days": 5,
            "incident_recovery_enabled": True,
        },
        depot_county=county,
        depot_city=city,
        depot_street=street,
        depot_number=number,
        depot_lat=lat,
        depot_lon=lon,
    )
    db.add(company)
    db.flush()
    return company


def create_vehicle(db, company_id, prefix: str, index: int) -> Vehicle:
    vehicle_types = [VehicleTypeEnum.VAN, VehicleTypeEnum.TRUCK, VehicleTypeEnum.CAR]
    fuel_types = [FuelTypeEnum.DIESEL, FuelTypeEnum.HYBRID, FuelTypeEnum.ELECTRIC]
    vehicle_type = vehicle_types[index % len(vehicle_types)]

    if vehicle_type == VehicleTypeEnum.TRUCK:
        capacity_kg, capacity_m3, consumption = 8000, 42, 19.5
    elif vehicle_type == VehicleTypeEnum.VAN:
        capacity_kg, capacity_m3, consumption = 2200, 14, 9.2
    else:
        capacity_kg, capacity_m3, consumption = 600, 4, 6.1

    status_cycle = [
        VehicleStatusEnum.DISPONIBIL,
        VehicleStatusEnum.DISPONIBIL,
        VehicleStatusEnum.DISPONIBIL,
        VehicleStatusEnum.REZERVAT,
        VehicleStatusEnum.SERVICE,
    ]

    vehicle = Vehicle(
        company_id=company_id,
        plate=f"{prefix}-{100 + index}-TMS",
        capacity_kg=capacity_kg,
        capacity_m3=capacity_m3,
        type=vehicle_type,
        status=status_cycle[index % len(status_cycle)],
        fuel_type=fuel_types[index % len(fuel_types)],
        avg_consumption=consumption,
        itp_expiry=TODAY + timedelta(days=120 + index * 11),
    )
    db.add(vehicle)
    return vehicle


def create_order(
    db,
    company_id,
    client_id,
    ref_prefix: str,
    sequence: int,
    local_sequence: int,
    pickup_zone: tuple,
    delivery_zone: tuple,
    status: OrderStatusEnum,
) -> Order:
    pickup_county, pickup_city, pickup_lat, pickup_lon = pickup_zone
    delivery_county, delivery_city, delivery_lat, delivery_lon = delivery_zone
    priority_cycle = [PriorityEnum.NORMAL, PriorityEnum.URGENT, PriorityEnum.CRITIC]
    cargo_cycle = [
        MarfaTypeEnum.STANDARD,
        MarfaTypeEnum.FRAGIL,
        MarfaTypeEnum.PERISABIL,
        MarfaTypeEnum.ADR,
    ]
    source_cycle = [OrderSourceEnum.PORTAL, OrderSourceEnum.API, OrderSourceEnum.PDF]

    deadline_offset = (sequence % 8) - 1
    earliest_offset = min(deadline_offset, deadline_offset - (sequence % 4))
    flexibility_days = sequence % 4
    priority = priority_cycle[sequence % len(priority_cycle)]
    cargo_type = cargo_cycle[sequence % len(cargo_cycle)]
    # Realistic order weights: 80-320kg for balanced fleet utilization
    # Volume scales with weight (typical density 150-250kg/m³)
    kg = 80 + (sequence % 32) * 7.5
    m3 = max(0.5, kg / 200 + (sequence % 10) * 0.08)
    pickup_service_minutes = 8 + sequence % 13
    delivery_service_minutes = 10 + sequence % 17
    is_problematic = sequence % 31 == 0
    was_postponed = sequence % 13 == 0
    problem_reason = "Adresa necesita confirmare" if is_problematic else None

    if status == OrderStatusEnum.PENDING:
        # Minimal deterministic strategy-comparison set (six orders):
        # 1-2 are high-priority satellite work; 3-6 form a dense local cluster.
        # Estimated minutes are 255/225 for satellite and 195 for local orders.
        # With one 540-minute driver/day, the first-day selections are:
        # GREEDY: 1+2, DENSITY: two local, HYBRID: 1+one local.
        earliest_offset = 0
        was_postponed = False
        is_problematic = False
        problem_reason = None
        if local_sequence == 1:
            priority = PriorityEnum.CRITIC
            deadline_offset = 0
            flexibility_days = 0
            kg, m3 = 420, 2.4
            pickup_service_minutes = delivery_service_minutes = 105
            cargo_type = MarfaTypeEnum.ADR
        elif local_sequence == 2:
            priority = PriorityEnum.URGENT
            deadline_offset = 2
            flexibility_days = 2
            kg, m3 = 360, 2.0
            pickup_service_minutes = delivery_service_minutes = 90
            cargo_type = MarfaTypeEnum.FRAGIL
        else:
            priority = PriorityEnum.NORMAL
            deadline_offset = 2
            flexibility_days = 2
            kg = 180 + local_sequence * 12
            m3 = 1.1 + (local_sequence - 3) * 0.12
            pickup_service_minutes = delivery_service_minutes = 75
            cargo_type = MarfaTypeEnum.PERISABIL if local_sequence == 6 else MarfaTypeEnum.STANDARD

    if status in (OrderStatusEnum.DELIVERED, OrderStatusEnum.FAILED):
        deadline_offset = -((sequence % 12) + 1)
    elif status in (OrderStatusEnum.PLANNED, OrderStatusEnum.IN_DELIVERY):
        deadline_offset = sequence % 3

    assigned_date = None
    if status in (
        OrderStatusEnum.PLANNED,
        OrderStatusEnum.IN_DELIVERY,
        OrderStatusEnum.DELIVERED,
        OrderStatusEnum.FAILED,
    ):
        assigned_date = TODAY + timedelta(days=max(-14, min(deadline_offset, 3)))

    pickup_lat = pickup_lat + ((sequence % 7) - 3) * 0.006
    pickup_lon = pickup_lon + ((sequence % 5) - 2) * 0.006
    delivery_lat = delivery_lat + ((sequence % 9) - 4) * 0.007
    delivery_lon = delivery_lon + ((sequence % 6) - 3) * 0.007

    if status == OrderStatusEnum.PENDING and local_sequence >= 3:
        dense_jitter = (local_sequence - 4.5) * 0.0008
        secondary_jitter = ((local_sequence % 2) * 2 - 1) * 0.0007
        pickup_lat = pickup_zone[2] + dense_jitter
        pickup_lon = pickup_zone[3] + secondary_jitter
        delivery_lat = delivery_zone[2] + dense_jitter + 0.0015
        delivery_lon = delivery_zone[3] + secondary_jitter - 0.0015

    order = Order(
        company_id=company_id,
        client_id=client_id,
        order_ref=f"{ref_prefix}-{sequence:04d}",
        address_pickup=f"Depozit {pickup_city}, Strada Logistica {sequence % 30 + 1}",
        pickup_county=pickup_county,
        pickup_city=pickup_city,
        pickup_street="Strada Logistica",
        pickup_number=str(sequence % 30 + 1),
        pickup_lat=pickup_lat,
        pickup_lon=pickup_lon,
        pickup_time_window_start=time(7 + sequence % 3, 0),
        pickup_time_window_end=time(11 + sequence % 2, 30),
        address_delivery=f"Client {delivery_city}, Bulevardul Distributiei {sequence % 80 + 1}",
        delivery_county=delivery_county,
        delivery_city=delivery_city,
        delivery_street="Bulevardul Distributiei",
        delivery_number=str(sequence % 80 + 1),
        delivery_lat=delivery_lat,
        delivery_lon=delivery_lon,
        delivery_time_window_start=time(12 + sequence % 2, 0),
        delivery_time_window_end=time(16 + sequence % 3, 30),
        kg=kg,
        m3=m3,
        pickup_service_minutes=pickup_service_minutes,
        delivery_service_minutes=delivery_service_minutes,
        service_time_source=(
            ServiceTimeSourceEnum.MANUAL
            if status == OrderStatusEnum.PENDING
            else ServiceTimeSourceEnum.AUTO
        ),
        type_marfa=cargo_type,
        priority=priority,
        delivery_deadline=TODAY + timedelta(days=deadline_offset),
        earliest_delivery_date=TODAY + timedelta(days=earliest_offset),
        flexibility_days=flexibility_days,
        assigned_delivery_date=assigned_date,
        status=status,
        tracking_token=unique_token(f"{ref_prefix}-{sequence}"),
        source=source_cycle[sequence % len(source_cycle)],
        attempts_count=1 if status == OrderStatusEnum.FAILED else 0,
        special_instructions=(
            "Necesita manipulare atenta."
            if sequence % 6 == 0
            else "Date demo generate pentru testare operationala."
        ),
        is_problematic=is_problematic,
        was_postponed=was_postponed,
        problem_reason=problem_reason,
    )
    if status == OrderStatusEnum.PENDING:
        # Avoid route-solver waiting time masking the strategy comparison.
        order.pickup_time_window_start = time(6, 0)
        order.pickup_time_window_end = time(20, 0)
        order.delivery_time_window_start = time(6, 0)
        order.delivery_time_window_end = time(20, 0)
    db.add(order)
    return order


def create_trip_with_orders(
    db,
    company_id,
    driver: Driver,
    vehicle: Vehicle,
    planning_session: PlanningSession,
    orders: list[Order],
    planned_day: date,
    status: TripStatusEnum,
    trip_index: int,
    lateness_minutes: int = 2,
    service_delta_minutes: int = 0,
    extra_cost: float = 0,
    failed_delivery_indexes: set[int] | None = None,
    planned_km: float | None = None,
    actual_km: float | None = None,
) -> Trip:
    start_hour = 7 + trip_index % 3
    failed_delivery_indexes = failed_delivery_indexes or set()
    planned_distance = planned_km if planned_km is not None else min(500, 95 + trip_index * 17)
    actual_distance = actual_km
    if status == TripStatusEnum.COMPLETED and actual_distance is None:
        actual_distance = round(planned_distance * (1.03 + (trip_index % 4) * 0.025), 2)
    planned_duration = 220 + len(orders) * 18 + trip_index % 5 * 8
    actual_duration = (
        planned_duration + max(0, lateness_minutes) + service_delta_minutes * len(orders)
        if status == TripStatusEnum.COMPLETED
        else None
    )
    trip = Trip(
        company_id=company_id,
        driver_id=driver.id,
        vehicle_id=vehicle.id,
        planning_session_id=planning_session.id,
        planned_date=planned_day,
        status=status,
        planned_km=planned_distance,
        actual_km=actual_distance if status == TripStatusEnum.COMPLETED else None,
        planned_duration_min=planned_duration,
        actual_duration_min=actual_duration,
        vehicle_plate_snapshot=vehicle.plate,
        vehicle_capacity_kg_snapshot=vehicle.capacity_kg,
        vehicle_capacity_m3_snapshot=vehicle.capacity_m3,
        started_at=dt((planned_day - TODAY).days, start_hour) if status != TripStatusEnum.PROPOSED else None,
        completed_at=dt((planned_day - TODAY).days, start_hour + 6) if status == TripStatusEnum.COMPLETED else None,
    )
    db.add(trip)
    db.flush()

    sequence = 1
    # Realistic routing: create all PICKUP stops first (consolidation at depot), then DELIVERY stops (route delivery)
    # This ensures peak load includes all orders on-board together during delivery phase

    # Phase 1: All PICKUP stops (consolidation)
    for idx, order in enumerate(orders):
        pickup_eta = dt((planned_day - TODAY).days, start_hour, idx * 5)
        stop_status = StopStatusEnum.PENDING
        if status == TripStatusEnum.COMPLETED:
            stop_status = StopStatusEnum.COMPLETED
        pickup_arrival = pickup_eta + timedelta(minutes=lateness_minutes)
        pickup_service = max(1, int(order.pickup_service_minutes or 10) + service_delta_minutes)

        db.add(
            TripStop(
                trip_id=trip.id,
                order_id=order.id,
                sequence=sequence,
                stop_type=StopTypeEnum.PICKUP,
                eta_planned=pickup_eta,
                eta_actual=pickup_arrival if stop_status == StopStatusEnum.COMPLETED else None,
                arrival_time=pickup_arrival if stop_status == StopStatusEnum.COMPLETED else None,
                departure_time=pickup_arrival + timedelta(minutes=pickup_service) if stop_status == StopStatusEnum.COMPLETED else None,
                status=stop_status,
                notes="Pickup confirmat" if stop_status == StopStatusEnum.COMPLETED else None,
                order_kg_snapshot=order.kg,
                order_m3_snapshot=order.m3,
            )
        )
        sequence += 1

    # Phase 2: All DELIVERY stops (route delivery)
    delivery_start = dt((planned_day - TODAY).days, start_hour + 1, 0)
    for idx, order in enumerate(orders):
        delivery_eta = delivery_start + timedelta(minutes=30 + idx * 15)
        stop_status = StopStatusEnum.PENDING
        if status == TripStatusEnum.COMPLETED:
            stop_status = (
                StopStatusEnum.FAILED
                if idx in failed_delivery_indexes
                else StopStatusEnum.COMPLETED
            )
        elif status == TripStatusEnum.INTERRUPTED and idx > len(orders) // 2:
            stop_status = StopStatusEnum.SKIPPED

        delivery_arrival = delivery_eta + timedelta(minutes=lateness_minutes)
        delivery_service = max(1, int(order.delivery_service_minutes or 10) + service_delta_minutes)
        if stop_status == StopStatusEnum.FAILED:
            order.status = OrderStatusEnum.FAILED

        db.add(
            TripStop(
                trip_id=trip.id,
                order_id=order.id,
                sequence=sequence,
                stop_type=StopTypeEnum.DELIVERY,
                eta_planned=delivery_eta,
                eta_actual=delivery_arrival if status == TripStatusEnum.COMPLETED else None,
                arrival_time=delivery_arrival if status == TripStatusEnum.COMPLETED else None,
                departure_time=delivery_arrival + timedelta(minutes=delivery_service) if status == TripStatusEnum.COMPLETED else None,
                status=stop_status,
                failure_reason=(
                    FailureReasonEnum.ABSENT
                    if stop_status == StopStatusEnum.FAILED
                    else FailureReasonEnum.OTHER if stop_status == StopStatusEnum.SKIPPED else None
                ),
                notes=(
                    "Destinatar absent"
                    if stop_status == StopStatusEnum.FAILED
                    else "Livrare finalizata" if stop_status == StopStatusEnum.COMPLETED else None
                ),
                order_kg_snapshot=order.kg,
                order_m3_snapshot=order.m3,
            )
        )
        sequence += 1

    if status == TripStatusEnum.INTERRUPTED and not extra_cost:
        extra_cost = 250
    upsert_trip_cost(
        db,
        trip,
        extra_cost=extra_cost,
        extra_reason="Incident rutier" if extra_cost else None,
    )
    return trip


def create_historical_kpi_data(
    db,
    company: Company,
    clients: list[User],
    drivers: list[Driver],
    vehicles: list[Vehicle],
    planning_sessions: list[PlanningSession],
    scenario: dict,
    company_index: int,
) -> dict:
    rng = random.Random(20260703 + company_index)
    historical_orders: list[Order] = []
    historical_trips: list[Trip] = []
    failed_orders: list[Order] = []
    sequence = company_index * 100000
    utilization_targets = [0.24, 0.46, 0.67, 0.83, 0.94, 1.07]
    lateness_pattern = [-6, 3, 14, 27, 43, 68]

    # Thirty-six completed trips across roughly ten weeks. The seeded load,
    # delay, service, distance and cost patterns deliberately cover every
    # analytics bucket rather than producing uniform demo charts.
    for trip_idx in range(36):
        day_offset = -(2 + trip_idx * 2)
        planned_day = TODAY + timedelta(days=day_offset)
        order_count = rng.randint(4, 8)
        vehicle = vehicles[trip_idx % len(vehicles)]
        target = utilization_targets[trip_idx % len(utilization_targets)]
        target_kg = float(vehicle.capacity_kg) * target
        target_m3 = float(vehicle.capacity_m3) * target * rng.uniform(0.88, 0.98)
        trip_orders = []

        for order_idx in range(order_count):
            sequence += 1
            pickup_zone = rng.choice(scenario["zones"])
            delivery_zone = rng.choice(scenario["zones"])
            created_at = dt(day_offset - rng.randint(1, 4), rng.randint(7, 17), rng.randint(0, 59))
            order = create_order(
                db=db,
                company_id=company.id,
                client_id=clients[(trip_idx + order_idx) % len(clients)].id,
                ref_prefix=f"{scenario['slug'].upper().replace('-', '')}-HIST",
                sequence=sequence,
                local_sequence=1000 + sequence,
                pickup_zone=pickup_zone,
                delivery_zone=delivery_zone,
                status=OrderStatusEnum.DELIVERED,
            )
            order.kg = round(target_kg / order_count * rng.uniform(0.94, 1.06), 2)
            order.m3 = round(target_m3 / order_count * rng.uniform(0.94, 1.06), 2)
            order.created_at = created_at
            order.updated_at = created_at + timedelta(hours=rng.randint(4, 18))
            order.delivery_deadline = planned_day
            order.earliest_delivery_date = planned_day - timedelta(days=2)
            order.flexibility_days = 2
            order.assigned_delivery_date = planned_day
            order.pickup_service_minutes = rng.randint(8, 22)
            order.delivery_service_minutes = rng.randint(10, 28)
            order.was_postponed = trip_idx % 9 == 0 and order_idx == 0
            historical_orders.append(order)
            trip_orders.append(order)

        db.flush()
        lateness = lateness_pattern[trip_idx % len(lateness_pattern)]
        planned_distance = round(72 + trip_idx * 6.5 + rng.uniform(-12, 18), 2)
        actual_distance = round(planned_distance * [0.94, 1.01, 1.07, 1.16][trip_idx % 4], 2)
        failed_indexes = {order_count - 1} if trip_idx % 8 == 7 else set()
        trip = create_trip_with_orders(
            db=db,
            company_id=company.id,
            driver=drivers[trip_idx % len(drivers)],
            vehicle=vehicle,
            planning_session=planning_sessions[trip_idx % len(planning_sessions)],
            orders=trip_orders,
            planned_day=planned_day,
            status=TripStatusEnum.COMPLETED,
            trip_index=trip_idx,
            lateness_minutes=lateness,
            service_delta_minutes=[-3, 0, 4, 9][trip_idx % 4],
            extra_cost=(180 + trip_idx * 12) if trip_idx % 7 == 0 else 0,
            failed_delivery_indexes=failed_indexes,
            planned_km=planned_distance,
            actual_km=actual_distance,
        )
        trip.created_at = dt(day_offset - 1, 16, 30)
        trip.started_at = dt(day_offset, 7 + trip_idx % 3, 0)
        trip.completed_at = dt(day_offset, 14 + trip_idx % 4, 20)
        historical_trips.append(trip)
        failed_orders.extend(trip_orders[index] for index in failed_indexes)

    # Additional resolved old orders vary daily KPI/status charts but have no
    # planning eligibility because every deadline is safely in the past.
    for loose_idx in range(72):
        sequence += 1
        day_offset = -rng.randint(3, 90)
        status = OrderStatusEnum.FAILED if loose_idx % 3 else OrderStatusEnum.CANCELLED
        created_at = dt(day_offset, rng.randint(7, 18), rng.randint(0, 59))
        order = create_order(
            db=db,
            company_id=company.id,
            client_id=clients[loose_idx % len(clients)].id,
            ref_prefix=f"{scenario['slug'].upper().replace('-', '')}-ARCHIVE",
            sequence=sequence,
            local_sequence=2000 + loose_idx,
            pickup_zone=rng.choice(scenario["zones"]),
            delivery_zone=rng.choice(scenario["zones"]),
            status=status,
        )
        order.created_at = created_at
        order.updated_at = created_at + timedelta(hours=rng.randint(2, 12))
        order.delivery_deadline = created_at.date() + timedelta(days=1)
        order.earliest_delivery_date = created_at.date()
        order.assigned_delivery_date = created_at.date() + timedelta(days=1)
        order.flexibility_days = 1
        historical_orders.append(order)
        if status == OrderStatusEnum.FAILED:
            failed_orders.append(order)

    db.flush()

    incident_count = 0
    for incident_idx, trip in enumerate(historical_trips[::3], start=1):
        incident_count += 1
        day_offset = (trip.planned_date - TODAY).days
        major = incident_idx % 4 == 0
        unresolved = incident_idx in (1, 5)
        zone = scenario["zones"][incident_idx % len(scenario["zones"])]
        db.add(Incident(
            trip_id=trip.id,
            driver_id=trip.driver_id,
            vehicle_id=trip.vehicle_id,
            type=IncidentTypeEnum.MAJOR if major else IncidentTypeEnum.MINOR,
            description=(
                "Defecțiune cu replanificare și întârziere semnificativă."
                if major else "Incident operațional minor în timpul livrării."
            ),
            location_lat=zone[2],
            location_lon=zone[3],
            created_at=dt(day_offset, 10 + incident_idx % 5, 20),
            resolved_at=None if unresolved else dt(day_offset, 12 + incident_idx % 5, 10),
            extra_cost_estimated=round(90 + incident_idx * 85.5, 2),
            impact_analysis={
                "affected_orders": 1 + incident_idx % 5,
                "affected_stops": 2 + incident_idx % 7,
                "delay_minutes": 18 + incident_idx * 17,
                "extra_recovery_km": 8 + incident_idx * 3,
                "recovery_needed": major,
                "historical": True,
            },
        ))

    for idx, order in enumerate(failed_orders[:36], start=1):
        db.add(Notification(
            company_id=company.id,
            user_id=order.client_id,
            order_id=order.id,
            type="FAILED_DELIVERY",
            channel=[
                NotificationChannelEnum.EMAIL,
                NotificationChannelEnum.SMS,
                NotificationChannelEnum.PUSH,
            ][idx % 3],
            content=f"Livrarea istorică {order.order_ref} a eșuat.",
            sent_at=order.created_at + timedelta(hours=5),
            delivered_at=order.created_at + timedelta(hours=5, minutes=2),
            status=NotificationStatusEnum.DELIVERED,
        ))

    return {
        "historical_orders": len(historical_orders),
        "historical_trips": len(historical_trips),
        "historical_incidents": incident_count,
    }


def validate_planning_showcase(
    db,
    pending_orders: list[Order],
    available_drivers: list[Driver],
) -> dict[str, list[list[str]]]:
    """Fail the seed if the three showcase distributions ever converge."""
    days = [TODAY + timedelta(days=offset) for offset in range(3)]
    capacity = _build_capacity_by_day_minutes(days, available_drivers)
    estimates = _build_estimated_minutes_by_order(db, pending_orders)
    previews = {}

    for strategy in (
        PlanningStrategyEnum.GREEDY_DEADLINE,
        PlanningStrategyEnum.MAX_DENSITY,
        PlanningStrategyEnum.HYBRID,
    ):
        result = distribute_orders_by_strategy(
            orders=pending_orders,
            strategy=strategy,
            date_start=days[0],
            date_end=days[-1],
            capacity_by_day_minutes=capacity,
            estimated_minutes_by_order=estimates,
        )
        result = _repair_deferred_distribution(
            distribution=result,
            date_start=days[0],
            date_end=days[-1],
            estimated_minutes_by_order=estimates,
        )
        previews[strategy.value] = [
            [order.order_ref for order in result["days"][day]]
            for day in days
        ]

    signatures = {tuple(tuple(day) for day in preview) for preview in previews.values()}
    if len(signatures) != 3:
        raise RuntimeError("Planning showcase invalid: strategy distributions are not distinct")

    return previews


def create_recovery_incident_scenarios(
    db,
    company: Company,
    clients: list[User],
    drivers: list[Driver],
    vehicles: list[Vehicle],
    planning_session: PlanningSession,
    scenario: dict,
) -> tuple[list[Trip], list[Incident], list[Order]]:
    """Create interrupted trips with valid cargo states for every recovery path."""
    recovery_trips = []
    recovery_incidents = []
    recovery_orders = []
    scenario_modes = ("PICKED_UP", "UNPICKED", "MIXED")

    for scenario_idx, mode in enumerate(scenario_modes):
        trip_orders = []
        for order_idx in range(4):
            sequence = 3000 + scenario_idx * 10 + order_idx
            zone = scenario["zones"][(scenario_idx + order_idx) % 2]
            order = create_order(
                db=db,
                company_id=company.id,
                client_id=clients[(scenario_idx + order_idx) % len(clients)].id,
                ref_prefix=f"{scenario['slug'].upper().replace('-', '')}-RECOVERY",
                sequence=sequence,
                local_sequence=3000 + scenario_idx * 10 + order_idx,
                pickup_zone=scenario["zones"][0],
                delivery_zone=zone,
                status=(
                    OrderStatusEnum.PLANNED
                    if mode == "UNPICKED"
                    else OrderStatusEnum.IN_DELIVERY
                ),
            )
            order.kg = 140 + scenario_idx * 30 + order_idx * 20
            order.m3 = round(0.7 + scenario_idx * 0.15 + order_idx * 0.1, 2)
            order.delivery_deadline = TODAY + timedelta(days=2)
            order.earliest_delivery_date = TODAY
            order.flexibility_days = 2
            order.assigned_delivery_date = TODAY
            order.pickup_time_window_start = time(6, 0)
            order.pickup_time_window_end = time(19, 0)
            order.delivery_time_window_start = time(6, 0)
            order.delivery_time_window_end = time(19, 0)
            order.pickup_service_minutes = 10 + order_idx
            order.delivery_service_minutes = 12 + order_idx
            order.is_problematic = False
            trip_orders.append(order)
            recovery_orders.append(order)

        db.flush()
        vehicle = vehicles[-(scenario_idx + 1)]
        vehicle.status = VehicleStatusEnum.AVARIAT
        trip = create_trip_with_orders(
            db=db,
            company_id=company.id,
            driver=drivers[4 + scenario_idx],
            vehicle=vehicle,
            planning_session=planning_session,
            orders=trip_orders,
            planned_day=TODAY,
            status=TripStatusEnum.INTERRUPTED,
            trip_index=50 + scenario_idx,
            extra_cost=300 + scenario_idx * 125,
            planned_km=48 + scenario_idx * 14,
        )
        db.flush()

        stops_by_order = {}
        for stop in trip.stops:
            stops_by_order.setdefault(stop.order_id, {})[stop.stop_type] = stop

        for order_idx, order in enumerate(trip_orders):
            pickup = stops_by_order[order.id][StopTypeEnum.PICKUP]
            delivery = stops_by_order[order.id][StopTypeEnum.DELIVERY]
            pickup.status = StopStatusEnum.PENDING
            delivery.status = StopStatusEnum.PENDING
            pickup.failure_reason = None
            delivery.failure_reason = None
            pickup.notes = None
            delivery.notes = None

            pickup_completed = mode == "PICKED_UP" or (mode == "MIXED" and order_idx < 2)
            delivery_completed = mode == "MIXED" and order_idx == 0

            if pickup_completed:
                pickup.status = StopStatusEnum.COMPLETED
                pickup.arrival_time = pickup.eta_planned
                pickup.departure_time = pickup.eta_planned + timedelta(
                    minutes=order.pickup_service_minutes
                )
                pickup.eta_actual = pickup.arrival_time
                order.status = OrderStatusEnum.IN_DELIVERY
            else:
                order.status = OrderStatusEnum.PLANNED

            if delivery_completed:
                delivery.status = StopStatusEnum.COMPLETED
                delivery.arrival_time = delivery.eta_planned
                delivery.departure_time = delivery.eta_planned + timedelta(
                    minutes=order.delivery_service_minutes
                )
                delivery.eta_actual = delivery.arrival_time
                order.status = OrderStatusEnum.DELIVERED

        incident = Incident(
            trip_id=trip.id,
            driver_id=trip.driver_id,
            vehicle_id=trip.vehicle_id,
            type=IncidentTypeEnum.MAJOR,
            description={
                "PICKED_UP": "Defecțiune după încărcare; marfa trebuie transferată și livrată.",
                "UNPICKED": "Vehicul indisponibil înainte de ridicare; comenzile pot fi recuperate sau amânate.",
                "MIXED": "Defecțiune în timpul rutei; există marfă livrată, la bord și încă neridicată.",
            }[mode],
            location_lat=scenario["zones"][1][2] + scenario_idx * 0.004,
            location_lon=scenario["zones"][1][3] + scenario_idx * 0.004,
            created_at=dt(0, 8 + scenario_idx, 30),
            resolved_at=None,
            recovery_trip_id=None,
            extra_cost_estimated=300 + scenario_idx * 125,
            impact_analysis=None,
        )
        db.add(incident)
        recovery_trips.append(trip)
        recovery_incidents.append(incident)

    return recovery_trips, recovery_incidents, recovery_orders


def seed_company(db, scenario: dict, company_index: int) -> dict:
    company = create_company(db, scenario)
    domain = scenario["domain"]

    manager = create_user(db, f"manager@{domain}", f"{scenario['name']} Manager", RoleEnum.MANAGER, company.id)
    dispatcher = create_user(db, f"dispatcher@{domain}", f"{scenario['name']} Dispatcher", RoleEnum.DISPECER, company.id)
    backup_dispatcher = create_user(db, f"dispatcher2@{domain}", f"{scenario['name']} Dispatcher 2", RoleEnum.DISPECER, company.id)
    third_dispatcher = create_user(db, f"dispatcher3@{domain}", f"{scenario['name']} Dispatcher 3", RoleEnum.DISPECER, company.id)
    clients = [
        create_user(db, f"client{i}@{domain}", f"{scenario['name']} Client {i}", RoleEnum.CLIENT, company.id)
        for i in range(1, 9)
    ]
    driver_users = [
        create_user(db, f"driver{i}@{domain}", f"{scenario['name']} Driver {i}", RoleEnum.SOFER, company.id)
        for i in range(1, 11)
    ]
    for i in range(1, scenario.get("inactive_driver_users", 0) + 1):
        create_user(
            db,
            f"inactive.driver{i}@{domain}",
            f"{scenario['name']} Inactive Driver {i}",
            RoleEnum.SOFER,
            company.id,
            is_active=False,
        )
    db.flush()

    vehicles = [
        create_vehicle(db, company.id, scenario["plate_prefix"], i)
        for i in range(1, 13)
    ]
    db.flush()

    drivers = []
    available_driver_count = scenario.get("available_drivers", 6)
    for index, driver_user in enumerate(driver_users):
        driver = Driver(
            company_id=company.id,
            user_id=driver_user.id,
            vehicle_id=vehicles[index].id,
            shift_start=time(6 + index % 3, 0),
            shift_end=time(15 + index % 4, 30),
            max_hours_day=8.0 + (index % 3) * 0.5,
            hours_driven_today=0.0 if index < 5 else 2.0,
            status=(
                DriverStatusEnum.AVAILABLE
                if index < available_driver_count
                else DriverStatusEnum.OFF_DUTY
            ),
            preferred_zones=[zone[1] for zone in scenario["zones"][index % len(scenario["zones"]):index % len(scenario["zones"]) + 1]],
        )
        db.add(driver)
        drivers.append(driver)
    db.flush()

    db.add_all(
        [
            SystemConfig(
                company_id=company.id,
                key="fuel_price_per_liter",
                value="7.45",
                data_type=ConfigDataTypeEnum.DECIMAL,
                description="Pret combustibil folosit in demo",
                updated_by=manager.id,
            ),
            SystemConfig(
                company_id=company.id,
                key="driver_hourly_rate",
                value="35.00",
                data_type=ConfigDataTypeEnum.DECIMAL,
                description="Tarif orar sofer",
                updated_by=manager.id,
            ),
            SystemConfig(
                company_id=company.id,
                key="vehicle_daily_amortization",
                value="160.00",
                data_type=ConfigDataTypeEnum.DECIMAL,
                description="Amortizare folosita per cursa",
                updated_by=manager.id,
            ),
            SystemConfig(
                company_id=company.id,
                key="vehicle_consumption_van",
                value="9.20",
                data_type=ConfigDataTypeEnum.DECIMAL,
                description="Consum implicit VAN",
                updated_by=manager.id,
            ),
            SystemConfig(
                company_id=company.id,
                key="vehicle_consumption_truck",
                value="19.50",
                data_type=ConfigDataTypeEnum.DECIMAL,
                description="Consum implicit TRUCK",
                updated_by=manager.id,
            ),
            SystemConfig(
                company_id=company.id,
                key="vehicle_consumption_car",
                value="6.10",
                data_type=ConfigDataTypeEnum.DECIMAL,
                description="Consum implicit CAR",
                updated_by=manager.id,
            ),
            SystemConfig(
                company_id=company.id,
                key="auto_replan_after_major_incident",
                value="true",
                data_type=ConfigDataTypeEnum.BOOLEAN,
                description="Activeaza recuperarea automata in scenariul demo",
                updated_by=manager.id,
            ),
        ]
    )

    orders = []
    statuses = (
        [OrderStatusEnum.PENDING] * 6
        + [OrderStatusEnum.PLANNED] * 10
        + [OrderStatusEnum.DELIVERED] * 8
        + [OrderStatusEnum.FAILED] * 4
        + [OrderStatusEnum.IN_DELIVERY] * 6
        + [OrderStatusEnum.CANCELLED] * 3
    )
    for sequence, status in enumerate(statuses, start=1):
        if status == OrderStatusEnum.PENDING and sequence <= 2:
            pickup_zone = scenario["zones"][1]
            delivery_zone = scenario["zones"][1]
        elif status == OrderStatusEnum.PENDING:
            pickup_zone = scenario["zones"][0]
            delivery_zone = scenario["zones"][0]
        else:
            pickup_zone = scenario["zones"][sequence % len(scenario["zones"])]
            if sequence % 9 == 0:
                delivery_zone = scenario["zones"][-1]
            elif sequence % 5 == 0:
                delivery_zone = scenario["zones"][0]
            else:
                delivery_zone = scenario["zones"][(sequence + 1) % len(scenario["zones"])]

        orders.append(
            create_order(
                db=db,
                company_id=company.id,
                client_id=clients[sequence % len(clients)].id,
                ref_prefix=f"{scenario['slug'].upper().replace('-', '')}",
                sequence=company_index * 1000 + sequence,
                local_sequence=sequence,
                pickup_zone=pickup_zone,
                delivery_zone=delivery_zone,
                status=status,
            )
        )
    db.flush()

    planning_sessions = []
    historical_strategies = [
        PlanningStrategyEnum.GREEDY_DEADLINE,
        PlanningStrategyEnum.MAX_DENSITY,
        PlanningStrategyEnum.HYBRID,
        PlanningStrategyEnum.AD_HOC,
    ]
    for offset in range(12):
        strategy = historical_strategies[offset % len(historical_strategies)]
        session_end = TODAY - timedelta(days=2 + offset * 6)
        session = PlanningSession(
            company_id=company.id,
            created_by=[dispatcher.id, backup_dispatcher.id, third_dispatcher.id][offset % 3],
            date_range_start=session_end - timedelta(days=2),
            date_range_end=session_end,
            strategy=strategy,
            status=PlanningStatusEnum.APPROVED,
            total_orders=14 + offset % 5,
            optimization_stats={
                "seeded": True,
                "planned_trips": 2 + offset % 4,
                "deferred_orders": offset % 3,
                "strategy_note": f"Historical demo for {strategy.value}",
            },
        )
        db.add(session)
        planning_sessions.append(session)
    db.flush()

    historical_summary = create_historical_kpi_data(
        db=db,
        company=company,
        clients=clients,
        drivers=drivers,
        vehicles=vehicles,
        planning_sessions=planning_sessions,
        scenario=scenario,
        company_index=company_index,
    )

    db.add(PlanningSession(
        company_id=company.id,
        created_by=dispatcher.id,
        date_range_start=TODAY,
        date_range_end=TODAY + timedelta(days=2),
        strategy=PlanningStrategyEnum.HYBRID,
        status=PlanningStatusEnum.DRAFT,
        total_orders=6,
        optimization_stats={
            "seeded": True,
            "purpose": "Three-strategy comparison workspace",
        },
    ))

    orders_by_status = {
        status: [order for order in orders if order.status == status]
        for status in (
            OrderStatusEnum.PLANNED,
            OrderStatusEnum.IN_DELIVERY,
            OrderStatusEnum.DELIVERED,
            OrderStatusEnum.FAILED,
        )
    }

    trips = []
    trip_statuses = [
        TripStatusEnum.COMPLETED,
        TripStatusEnum.APPROVED,
        TripStatusEnum.IN_PROGRESS,
    ]
    for trip_index, trip_status in enumerate(trip_statuses):
        if trip_status == TripStatusEnum.COMPLETED:
            # Use 5-6 orders per COMPLETED trip for good utilization
            trip_orders = orders_by_status[OrderStatusEnum.DELIVERED][
                trip_index * 6: trip_index * 6 + 6
            ]
        elif trip_status == TripStatusEnum.IN_PROGRESS:
            # Use 5-6 orders for active trip
            trip_orders = (
                orders_by_status[OrderStatusEnum.IN_DELIVERY]
                + orders_by_status[OrderStatusEnum.PLANNED]
            )[:6]
        else:
            # Use 5-6 orders per APPROVED trip
            trip_orders = orders_by_status[OrderStatusEnum.PLANNED][
                trip_index * 6: trip_index * 6 + 6
            ]
        if not trip_orders:
            continue
        planned_day = {
            TripStatusEnum.COMPLETED: TODAY - timedelta(days=1),
            TripStatusEnum.APPROVED: TODAY + timedelta(days=1),
            TripStatusEnum.IN_PROGRESS: TODAY,
        }[trip_status]
        # Select vehicle based on order weights (realistic capacity matching)
        selected_vehicle = select_vehicle_for_orders(trip_orders, vehicles, trip_index)
        trip = create_trip_with_orders(
            db=db,
            company_id=company.id,
            driver=drivers[trip_index % len(drivers)],
            vehicle=selected_vehicle,
            planning_session=planning_sessions[trip_index % len(planning_sessions)],
            orders=trip_orders,
            planned_day=planned_day,
            status=trip_status,
            trip_index=trip_index,
        )
        trips.append(trip)
    db.flush()

    recovery_trips, recovery_incidents, recovery_orders = create_recovery_incident_scenarios(
        db=db,
        company=company,
        clients=clients,
        drivers=drivers,
        vehicles=vehicles,
        planning_session=planning_sessions[0],
        scenario=scenario,
    )
    trips.extend(recovery_trips)
    orders.extend(recovery_orders)
    db.flush()

    if trips:
        db.add(
            Incident(
                trip_id=trips[0].id,
                driver_id=trips[0].driver_id,
                vehicle_id=trips[0].vehicle_id,
                type=IncidentTypeEnum.MINOR,
                description="Intarziere la incarcare rezolvata de dispecer.",
                location_lat=scenario["zones"][1][2],
                location_lon=scenario["zones"][1][3],
                created_at=dt(-3, 9, 10),
                resolved_at=dt(-3, 10, 5),
                extra_cost_estimated=90,
                impact_analysis={"delay_minutes": 35, "recovery_needed": False},
            )
        )

    for trip in trips[:3]:
        db.add_all(
            [
                ChatMessage(
                    trip_id=trip.id,
                    sender_id=dispatcher.id,
                    message_text="Confirma statusul la urmatorul stop.",
                    sent_at=dt((trip.planned_date - TODAY).days, 9, 0),
                    read_at=dt((trip.planned_date - TODAY).days, 9, 5),
                    message_type=MessageTypeEnum.TEXT,
                    metadata_={"source": "seed"},
                ),
                ChatMessage(
                    trip_id=trip.id,
                    sender_id=trip.driver.user_id,
                    message_text="Confirmat, continui ruta conform planului.",
                    sent_at=dt((trip.planned_date - TODAY).days, 9, 8),
                    read_at=dt((trip.planned_date - TODAY).days, 9, 9),
                    message_type=MessageTypeEnum.TEXT,
                    metadata_={"source": "seed"},
                ),
            ]
        )

    for index, order in enumerate(orders[:18]):
        status = NotificationStatusEnum.DELIVERED if index % 4 else NotificationStatusEnum.SENT
        db.add(
            Notification(
                company_id=company.id,
                user_id=order.client_id,
                order_id=order.id,
                type="ORDER_STATUS",
                channel=NotificationChannelEnum.EMAIL,
                content=f"Actualizare pentru comanda {order.order_ref}",
                sent_at=dt(-(index % 5), 8 + index % 8, 15),
                delivered_at=dt(-(index % 5), 8 + index % 8, 17) if status == NotificationStatusEnum.DELIVERED else None,
                status=status,
            )
        )

    for offset in range(1, 31):
        db.add(
            DailyReport(
                company_id=company.id,
                report_date=TODAY - timedelta(days=offset),
                pdf_path=f"/reports/{scenario['slug']}/{TODAY - timedelta(days=offset)}.pdf",
                sent_to_email=f"manager@{domain}",
                generated_at=dt(-offset, 18, 30),
                kpi_snapshot={
                    "orders": 14 + (offset * 7) % 29,
                    "delivered": 11 + (offset * 5) % 23,
                    "failed": offset % 5,
                    "planned_km": 620 + (offset * 137) % 1250,
                },
            )
        )

    audit_actions = [
        "PLANNING_GENERATED",
        "TRIP_APPROVED",
        "VEHICLE_ASSIGNED",
        "ORDER_UPDATED",
        "INCIDENT_REVIEWED",
        "COST_CONFIG_UPDATED",
    ]
    for audit_idx in range(24):
        db.add(AuditLog(
            company_id=company.id,
            user_id=[manager.id, dispatcher.id, backup_dispatcher.id, third_dispatcher.id][audit_idx % 4],
            action=audit_actions[audit_idx % len(audit_actions)],
            entity_type=["PlanningSession", "Trip", "Vehicle", "Order", "Incident", "SystemConfig"][audit_idx % 6],
            entity_id=company.id,
            old_value=None,
            new_value={"seeded": True, "sequence": audit_idx + 1},
            ip_address="127.0.0.1",
            user_agent="seed_rich_demo_data.py",
            timestamp=dt(-(audit_idx % 20), 8 + audit_idx % 9, audit_idx * 7 % 60),
        ))

    db.flush()
    pending_orders = [order for order in orders if order.status == OrderStatusEnum.PENDING]
    available_drivers = [driver for driver in drivers if driver.status == DriverStatusEnum.AVAILABLE]
    planning_previews = validate_planning_showcase(db, pending_orders, available_drivers)

    return {
        "company": company,
        "manager_email": f"manager@{domain}",
        "users": 1 + 3 + len(clients) + len(driver_users),
        "vehicles": len(vehicles),
        "drivers": len(drivers),
        "orders": len(orders),
        "trips": len(trips),
        "historical_orders": historical_summary["historical_orders"],
        "historical_trips": historical_summary["historical_trips"],
        "historical_incidents": historical_summary["historical_incidents"],
        "recovery_incidents": len(recovery_incidents),
        "planning_previews": planning_previews,
    }


def seed_rich_demo_data() -> None:
    db = SessionLocal()
    try:
        print("Cleaning database...")
        cleanup_database(db)

        superadmin = create_user(
            db,
            email="admin@platform.test",
            full_name="Platform Super Admin",
            role=RoleEnum.SUPER_ADMIN,
            company_id=None,
        )
        db.flush()

        summaries = []
        for index, scenario in enumerate(COMPANY_SCENARIOS, start=1):
            summaries.append(seed_company(db, scenario, index))

        db.commit()

        print("\nRich demo seed completed successfully.")
        print(f"Password for every user: {PASSWORD}")
        print(f"Super admin: {superadmin.email}")
        for summary in summaries:
            company = summary["company"]
            print(
                f"- {company.name}: "
                f"{summary['users']} users, "
                f"{summary['vehicles']} vehicles, "
                f"{summary['drivers']} drivers, "
                f"{summary['orders']} orders, "
                f"{summary['trips']} trips, "
                f"{summary['historical_orders']} historical orders, "
                f"{summary['historical_trips']} historical trips, "
                f"{summary['historical_incidents']} historical incidents, "
                f"{summary['recovery_incidents']} actionable recovery incidents"
            )
            print(f"  {summary['manager_email']}")
            print("  Planning comparison: today through today + 2 days (6 eligible orders)")
            for strategy, preview in summary["planning_previews"].items():
                print(f"    {strategy}: {preview}")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_rich_demo_data()
