"""
Reset and seed a large demo dataset.

This script is intentionally destructive: it removes existing app data before
creating a fresh, populated scenario for local/demo use.

Run from the backend directory:
    python seed_rich_demo_data.py
"""

import hashlib
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


PASSWORD = "helloWorld"
TODAY = date.today()
NOW = datetime.now(timezone.utc)


COMPANY_SCENARIOS = [
    {
        "name": "Atlas Freight",
        "slug": "atlas-freight",
        "domain": "atlasfreight.com",
        "plan": PlanEnum.PRO,
        "depot": ("Cluj", "Cluj-Napoca", "Strada Fabricii", "10", 46.7860, 23.6200),
        "plate_prefix": "CJ",
        "zones": [
            ("Cluj", "Cluj-Napoca", 46.7712, 23.6236),
            ("Cluj", "Floresti", 46.7468, 23.4936),
            ("Bihor", "Oradea", 47.0465, 21.9189),
            ("Alba", "Alba Iulia", 46.0686, 23.5715),
        ],
    },
    {
        "name": "Rapid Courier",
        "slug": "rapid-courier",
        "domain": "rapidcourier.com",
        "plan": PlanEnum.PRO,
        "depot": ("Bucuresti", "Bucuresti", "Soseaua Industriilor", "42", 44.4268, 26.1025),
        "plate_prefix": "B",
        "available_drivers": 3,
        "zones": [
            ("Bucuresti", "Bucuresti", 44.4268, 26.1025),
            ("Ilfov", "Otopeni", 44.5500, 26.0667),
            ("Prahova", "Ploiesti", 44.9361, 26.0129),
            ("Arges", "Pitesti", 44.8565, 24.8692),
        ],
    },
    {
        "name": "Cold Chain Logistics",
        "slug": "cold-chain-logistics",
        "domain": "coldchainlogistics.com",
        "plan": PlanEnum.BASIC,
        "depot": ("Timis", "Timisoara", "Calea Sagului", "115", 45.7489, 21.2087),
        "plate_prefix": "TM",
        "zones": [
            ("Timis", "Timisoara", 45.7489, 21.2087),
            ("Arad", "Arad", 46.1866, 21.3123),
            ("Hunedoara", "Deva", 45.8833, 22.9000),
            ("Caras-Severin", "Resita", 45.3008, 21.8892),
        ],
    },
    {
        "name": "Moldova Distribution",
        "slug": "moldova-distribution",
        "domain": "moldovadistribution.com",
        "plan": PlanEnum.BASIC,
        "depot": ("Iasi", "Iasi", "Bulevardul Chimiei", "7", 47.1585, 27.6014),
        "plate_prefix": "IS",
        "zones": [
            ("Iasi", "Iasi", 47.1585, 27.6014),
            ("Bacau", "Bacau", 46.5670, 26.9146),
            ("Neamt", "Piatra Neamt", 46.9296, 26.3770),
            ("Suceava", "Suceava", 47.6514, 26.2556),
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


def create_user(db, email: str, full_name: str, role: RoleEnum, company_id=None) -> User:
    user = User(
        email=email,
        password_hash=hash_password(PASSWORD),
        full_name=full_name,
        role=role,
        company_id=company_id,
        is_active=True,
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
        # Strategy comparison playground:
        # - 1..8: urgent but geographically sparse
        # - 9..20: dense, low-priority city work
        # - 21..26: urgent and dense
        # - 27..32: bulky/long-haul orders that stress capacity/time
        # The three strategies should now disagree on which orders are placed
        # first in a 2-3 day planning interval.
        earliest_offset = 0
        is_problematic = False
        problem_reason = None

        if local_sequence <= 8:
            # Small urgent parcels - high priority
            priority = PriorityEnum.CRITIC if local_sequence % 2 else PriorityEnum.URGENT
            deadline_offset = 0 if local_sequence <= 5 else 1
            flexibility_days = 1
            kg = 120 + (local_sequence % 5) * 30  # 120-270kg
            m3 = max(0.6, kg / 180 + (local_sequence % 3) * 0.1)
            pickup_service_minutes = 40
            delivery_service_minutes = 45
            cargo_type = MarfaTypeEnum.FRAGIL if local_sequence % 3 else MarfaTypeEnum.ADR
        elif local_sequence <= 20:
            # Standard city work - normal priority
            priority = PriorityEnum.NORMAL
            deadline_offset = 2
            flexibility_days = 2
            kg = 100 + (local_sequence % 6) * 25  # 100-250kg
            m3 = max(0.5, kg / 200 + (local_sequence % 3) * 0.05)
            pickup_service_minutes = 35
            delivery_service_minutes = 40
            cargo_type = MarfaTypeEnum.STANDARD
        elif local_sequence <= 26:
            # Urgent/perishable items - higher priority
            priority = PriorityEnum.CRITIC if local_sequence % 3 == 0 else PriorityEnum.URGENT
            deadline_offset = 1
            flexibility_days = 1
            kg = 150 + (local_sequence % 6) * 30  # 150-330kg
            m3 = max(0.8, kg / 180 + (local_sequence % 3) * 0.1)
            pickup_service_minutes = 45
            delivery_service_minutes = 45
            cargo_type = MarfaTypeEnum.PERISABIL
            was_postponed = local_sequence % 5 == 0
        else:
            # Bulk consolidation orders
            priority = PriorityEnum.NORMAL if local_sequence % 3 else PriorityEnum.URGENT
            deadline_offset = 2
            flexibility_days = 2
            kg = 200 + (local_sequence % 7) * 50  # 200-550kg
            m3 = max(1.0, kg / 200 + (local_sequence % 4) * 0.15)
            pickup_service_minutes = 75
            delivery_service_minutes = 80
            cargo_type = MarfaTypeEnum.STANDARD

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

    if status == OrderStatusEnum.PENDING and 9 <= local_sequence <= 26:
        dense_jitter = ((local_sequence % 9) - 4) * 0.0012
        secondary_jitter = ((local_sequence % 7) - 3) * 0.001
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
) -> Trip:
    start_hour = 7 + trip_index % 3
    trip = Trip(
        company_id=company_id,
        driver_id=driver.id,
        vehicle_id=vehicle.id,
        planning_session_id=planning_session.id,
        planned_date=planned_day,
        status=status,
        planned_km=min(500, 95 + trip_index * 17),
        actual_km=(
            min(500, 103 + trip_index * 19)
            if status == TripStatusEnum.COMPLETED
            else None
        ),
        planned_duration_min=260 + trip_index * 18,
        actual_duration_min=(278 + trip_index * 21) if status == TripStatusEnum.COMPLETED else None,
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

        db.add(
            TripStop(
                trip_id=trip.id,
                order_id=order.id,
                sequence=sequence,
                stop_type=StopTypeEnum.PICKUP,
                eta_planned=pickup_eta,
                eta_actual=pickup_eta + timedelta(minutes=4) if stop_status == StopStatusEnum.COMPLETED else None,
                arrival_time=pickup_eta + timedelta(minutes=2) if stop_status == StopStatusEnum.COMPLETED else None,
                departure_time=pickup_eta + timedelta(minutes=8) if stop_status == StopStatusEnum.COMPLETED else None,
                status=stop_status,
                notes="Pickup confirmat" if stop_status == StopStatusEnum.COMPLETED else None,
            )
        )
        sequence += 1

    # Phase 2: All DELIVERY stops (route delivery)
    delivery_start = dt((planned_day - TODAY).days, start_hour + 1, 0)
    for idx, order in enumerate(orders):
        delivery_eta = delivery_start + timedelta(minutes=30 + idx * 15)
        stop_status = StopStatusEnum.PENDING
        if status == TripStatusEnum.COMPLETED:
            stop_status = StopStatusEnum.COMPLETED
        elif status == TripStatusEnum.INTERRUPTED and idx > len(orders) // 2:
            stop_status = StopStatusEnum.SKIPPED

        db.add(
            TripStop(
                trip_id=trip.id,
                order_id=order.id,
                sequence=sequence,
                stop_type=StopTypeEnum.DELIVERY,
                eta_planned=delivery_eta,
                eta_actual=delivery_eta + timedelta(minutes=5) if stop_status == StopStatusEnum.COMPLETED else None,
                arrival_time=delivery_eta + timedelta(minutes=2) if stop_status == StopStatusEnum.COMPLETED else None,
                departure_time=delivery_eta + timedelta(minutes=15) if stop_status == StopStatusEnum.COMPLETED else None,
                status=stop_status,
                failure_reason=FailureReasonEnum.OTHER if stop_status == StopStatusEnum.SKIPPED else None,
                notes="Livrare finalizata" if stop_status == StopStatusEnum.COMPLETED else None,
            )
        )
        sequence += 1

    extra_cost = 250 if status == TripStatusEnum.INTERRUPTED else 0
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
    planning_session: PlanningSession,
    scenario: dict,
    company_index: int,
) -> dict:
    historical_orders = []
    delivered_orders = []
    failed_orders = []

    daily_order_counts = {
        -1: 12,
        -2: 4,
        -3: 35,
        -4: 2,
        -5: 18,
        -6: 7,
        -7: 28,
        -9: 44,
        -11: 9,
        -14: 31,
        -18: 6,
        -23: 22,
        -27: 14,
    }
    historical_sequence = 0

    for day_offset, order_count in daily_order_counts.items():
        for daily_index in range(1, order_count + 1):
            historical_sequence += 1

            if daily_index % 17 == 0:
                status = OrderStatusEnum.CANCELLED
            elif daily_index % 9 == 0:
                status = OrderStatusEnum.FAILED
            else:
                status = OrderStatusEnum.DELIVERED

            created_at = dt(
                day_offset,
                6 + (daily_index % 13),
                (daily_index * 11 + company_index * 7) % 60,
            )
            sequence = company_index * 10000 + historical_sequence
            local_sequence = 200 + historical_sequence

            pickup_zone = scenario["zones"][daily_index % len(scenario["zones"])]
            delivery_zone = scenario["zones"][(daily_index + company_index) % len(scenario["zones"])]

            order = create_order(
                db=db,
                company_id=company.id,
                client_id=clients[daily_index % len(clients)].id,
                ref_prefix=f"{scenario['slug'].upper().replace('-', '')}HIST",
                sequence=sequence,
                local_sequence=local_sequence,
                pickup_zone=pickup_zone,
                delivery_zone=delivery_zone,
                status=status,
            )
            order.created_at = created_at
            order.updated_at = created_at + timedelta(hours=2)
            order.delivery_deadline = created_at.date() + timedelta(days=2)
            order.earliest_delivery_date = created_at.date()
            order.flexibility_days = 2
            order.assigned_delivery_date = created_at.date() + timedelta(days=1)
            order.was_postponed = daily_index % 11 == 0

            if status == OrderStatusEnum.DELIVERED:
                delivered_orders.append(order)
            elif status == OrderStatusEnum.FAILED:
                failed_orders.append(order)

            historical_orders.append(order)

    db.flush()

    historical_trips = []
    for trip_idx in range(6):
        # Use 6-8 orders per historical trip for realistic utilization
        start_idx = trip_idx * 7
        end_idx = min(start_idx + 7, len(delivered_orders))
        trip_orders = delivered_orders[start_idx:end_idx]
        if not trip_orders:
            continue

        planned_day = TODAY - timedelta(days=trip_idx * 4 + company_index)
        # Select vehicle based on order weights (realistic capacity matching)
        selected_vehicle = select_vehicle_for_orders(trip_orders, vehicles, trip_idx)
        trip = create_trip_with_orders(
            db=db,
            company_id=company.id,
            driver=drivers[trip_idx % len(drivers)],
            vehicle=selected_vehicle,
            planning_session=planning_session,
            orders=trip_orders,
            planned_day=planned_day,
            status=TripStatusEnum.COMPLETED,
            trip_index=trip_idx,
        )
        trip.created_at = dt((planned_day - TODAY).days, 6, 30)
        trip.started_at = dt((planned_day - TODAY).days, 7, 15)
        trip.completed_at = dt((planned_day - TODAY).days, 15, 10)
        historical_trips.append(trip)

    db.flush()

    if historical_trips:
        for incident_idx, trip in enumerate(historical_trips[:3], start=1):
            incident_day_offset = (trip.planned_date - TODAY).days
            db.add(
                Incident(
                    trip_id=trip.id,
                    driver_id=trip.driver_id,
                    vehicle_id=trip.vehicle_id,
                    type=IncidentTypeEnum.MINOR if incident_idx < 3 else IncidentTypeEnum.MAJOR,
                    description=(
                        "Incident istoric rezolvat pentru KPI-uri "
                        f"#{incident_idx}."
                    ),
                    location_lat=scenario["zones"][incident_idx % len(scenario["zones"])][2],
                    location_lon=scenario["zones"][incident_idx % len(scenario["zones"])][3],
                    created_at=dt(incident_day_offset, 10, 20),
                    resolved_at=dt(incident_day_offset, 11 + incident_idx, 5),
                    extra_cost_estimated=80 * incident_idx,
                    impact_analysis={
                        "delay_minutes": 20 * incident_idx,
                        "recovery_needed": False,
                        "historical": True,
                    },
                )
            )

    for idx, order in enumerate(failed_orders, start=1):
        db.add(
            Notification(
                company_id=company.id,
                user_id=order.client_id,
                order_id=order.id,
                type="FAILED_DELIVERY",
                channel=NotificationChannelEnum.EMAIL,
                content=f"Livrarea istorica {order.order_ref} a esuat.",
                sent_at=order.created_at + timedelta(hours=5),
                delivered_at=order.created_at + timedelta(hours=5, minutes=2),
                status=NotificationStatusEnum.DELIVERED,
            )
        )

    return {
        "historical_orders": len(historical_orders),
        "historical_trips": len(historical_trips),
    }


def seed_company(db, scenario: dict, company_index: int) -> dict:
    company = create_company(db, scenario)
    domain = scenario["domain"]

    manager = create_user(db, f"manager@{domain}", f"{scenario['name']} Manager", RoleEnum.MANAGER, company.id)
    dispatcher = create_user(db, f"dispatcher@{domain}", f"{scenario['name']} Dispatcher", RoleEnum.DISPECER, company.id)
    backup_dispatcher = create_user(db, f"dispatcher2@{domain}", f"{scenario['name']} Dispatcher 2", RoleEnum.DISPECER, company.id)
    clients = [
        create_user(db, f"client{i}@{domain}", f"{scenario['name']} Client {i}", RoleEnum.CLIENT, company.id)
        for i in range(1, 7)
    ]
    driver_users = [
        create_user(db, f"driver{i}@{domain}", f"{scenario['name']} Driver {i}", RoleEnum.SOFER, company.id)
        for i in range(1, 9)
    ]
    db.flush()

    vehicles = [
        create_vehicle(db, company.id, scenario["plate_prefix"], i)
        for i in range(1, 11)
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
        [OrderStatusEnum.PENDING] * 32
        + [OrderStatusEnum.PLANNED] * 12
        + [OrderStatusEnum.DELIVERED] * 10
        + [OrderStatusEnum.FAILED] * 4
        + [OrderStatusEnum.IN_DELIVERY] * 3
        + [OrderStatusEnum.CANCELLED] * 2
    )
    for sequence, status in enumerate(statuses, start=1):
        if status == OrderStatusEnum.PENDING and sequence <= 8:
            pickup_zone = scenario["zones"][sequence % len(scenario["zones"])]
            delivery_zone = scenario["zones"][(sequence + 2) % len(scenario["zones"])]
        elif status == OrderStatusEnum.PENDING and sequence <= 26:
            pickup_zone = scenario["zones"][0]
            delivery_zone = scenario["zones"][0]
        elif status == OrderStatusEnum.PENDING:
            pickup_zone = scenario["zones"][sequence % len(scenario["zones"])]
            delivery_zone = scenario["zones"][-1]
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
    for offset, strategy in enumerate(
        [
            PlanningStrategyEnum.GREEDY_DEADLINE,
            PlanningStrategyEnum.MAX_DENSITY,
            PlanningStrategyEnum.HYBRID,
            PlanningStrategyEnum.AD_HOC,
        ]
    ):
        session = PlanningSession(
            company_id=company.id,
            created_by=dispatcher.id,
            date_range_start=TODAY + timedelta(days=offset - 2),
            date_range_end=TODAY + timedelta(days=offset + 2),
            strategy=strategy,
            status=PlanningStatusEnum.APPROVED if offset < 3 else PlanningStatusEnum.PROPOSED,
            total_orders=18 + offset * 4,
            optimization_stats={
                "seeded": True,
                "planned_trips": 3 + offset,
                "deferred_orders": offset,
                "strategy_note": f"Demo data for {strategy.value}",
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
        planning_session=planning_sessions[0],
        scenario=scenario,
        company_index=company_index,
    )

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
        TripStatusEnum.COMPLETED,
        TripStatusEnum.APPROVED,
        TripStatusEnum.IN_PROGRESS,
        TripStatusEnum.INTERRUPTED,
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
        elif trip_status == TripStatusEnum.INTERRUPTED:
            # Use 5 orders for interrupted trip
            trip_orders = (
                orders_by_status[OrderStatusEnum.FAILED]
                + orders_by_status[OrderStatusEnum.PLANNED]
            )[:5]
        else:
            # Use 5-6 orders per APPROVED trip
            trip_orders = orders_by_status[OrderStatusEnum.PLANNED][
                trip_index * 6: trip_index * 6 + 6
            ]
        if not trip_orders:
            continue
        planned_day = (
            TODAY - timedelta(days=trip_index)
            if trip_status == TripStatusEnum.COMPLETED
            else TODAY + timedelta(days=trip_index - 3)
        )
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

    if trips:
        major_trip = trips[-1]
        recovery_trip = trips[1] if len(trips) > 1 else None
        db.add(
            Incident(
                trip_id=major_trip.id,
                driver_id=major_trip.driver_id,
                vehicle_id=major_trip.vehicle_id,
                type=IncidentTypeEnum.MAJOR,
                description="Avarie vehicul cu impact asupra livrarilor ramase.",
                location_lat=scenario["zones"][0][2] + 0.02,
                location_lon=scenario["zones"][0][3] + 0.02,
                created_at=dt(-1, 11, 20),
                resolved_at=None,
                recovery_trip_id=recovery_trip.id if recovery_trip else None,
                extra_cost_estimated=750,
                impact_analysis={
                    "affected_orders": 4,
                    "delay_minutes": 160,
                    "recovery_needed": True,
                },
            )
        )
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

    for offset in range(1, 8):
        db.add(
            DailyReport(
                company_id=company.id,
                report_date=TODAY - timedelta(days=offset),
                pdf_path=f"/reports/{scenario['slug']}/{TODAY - timedelta(days=offset)}.pdf",
                sent_to_email=f"manager@{domain}",
                generated_at=dt(-offset, 18, 30),
                kpi_snapshot={
                    "orders": 34 + offset,
                    "delivered": 28 + offset,
                    "failed": offset % 3,
                    "planned_km": 1200 + offset * 75,
                },
            )
        )

    db.add(
        AuditLog(
            company_id=company.id,
            user_id=manager.id,
            action="SEED_RICH_DEMO_DATA",
            entity_type="Company",
            entity_id=company.id,
            old_value=None,
            new_value={"orders": len(orders), "trips": len(trips)},
            ip_address="127.0.0.1",
            user_agent="seed_rich_demo_data.py",
            timestamp=NOW,
        )
    )

    return {
        "company": company,
        "manager_email": f"manager@{domain}",
        "users": 1 + 2 + len(clients) + len(driver_users),
        "vehicles": len(vehicles),
        "drivers": len(drivers),
        "orders": len(orders),
        "trips": len(trips),
        "historical_orders": historical_summary["historical_orders"],
        "historical_trips": historical_summary["historical_trips"],
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
                f"{summary['historical_trips']} historical trips"
            )
            print(f"  {summary['manager_email']}")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_rich_demo_data()
