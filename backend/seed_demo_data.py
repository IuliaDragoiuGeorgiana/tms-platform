import secrets
from datetime import date, time, timedelta

from app.database import SessionLocal
from app.core.security import hash_password

from app.models.company import Company, PlanEnum
from app.models.user import User, RoleEnum
from app.models.vehicle import Vehicle, VehicleTypeEnum, VehicleStatusEnum, FuelTypeEnum
from app.models.driver import Driver, DriverStatusEnum
from app.models.order import (
    Order,
    MarfaTypeEnum,
    PriorityEnum,
    OrderStatusEnum,
    OrderSourceEnum,
)


DEMO_COMPANY_SLUG = "demo-logistics"


def get_or_create_company(db):
    company = db.query(Company).filter(Company.slug == DEMO_COMPANY_SLUG).first()

    if company:
        print(f"Compania există deja: {company.name}")
        return company

    company = Company(
        name="Demo Logistics SRL",
        slug=DEMO_COMPANY_SLUG,
        is_active=True,
        plan=PlanEnum.BASIC,
        max_vehicles=20,
        max_users=50,
    )

    db.add(company)
    db.commit()
    db.refresh(company)

    print(f"Companie creată: {company.name}")
    return company


def get_or_create_user(
    db,
    email: str,
    full_name: str,
    role: RoleEnum,
    company_id=None,
    password: str = "Demo1234",
    phone: str | None = None,
    is_approved: bool = True,
    must_change_password: bool = False,
):
    user = db.query(User).filter(User.email == email).first()

    if user:
        print(f"User existent: {email}")
        return user

    user = User(
        email=email,
        password_hash=hash_password(password),
        full_name=full_name,
        role=role,
        company_id=company_id,
        is_active=True,
        is_approved=is_approved,
        must_change_password=must_change_password,
        phone=phone,
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    print(f"User creat: {email} / parola: {password}")
    return user


def get_or_create_vehicle(
    db,
    company_id,
    plate: str,
    capacity_kg: float,
    capacity_m3: float,
    vehicle_type: VehicleTypeEnum,
    fuel_type: FuelTypeEnum,
    avg_consumption: float,
):
    vehicle = db.query(Vehicle).filter(Vehicle.plate == plate).first()

    if vehicle:
        print(f"Vehicul existent: {plate}")
        return vehicle

    vehicle = Vehicle(
        company_id=company_id,
        plate=plate,
        capacity_kg=capacity_kg,
        capacity_m3=capacity_m3,
        type=vehicle_type,
        status=VehicleStatusEnum.DISPONIBIL,
        fuel_type=fuel_type,
        avg_consumption=avg_consumption,
        itp_expiry=date(2026, 12, 31),
    )

    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)

    print(f"Vehicul creat: {plate}")
    return vehicle


def get_or_create_driver(db, company_id, user_id, vehicle_id):
    driver = db.query(Driver).filter(Driver.user_id == user_id).first()

    if driver:
        print(f"Driver existent pentru user_id={user_id}")
        return driver

    driver = Driver(
        company_id=company_id,
        user_id=user_id,
        vehicle_id=vehicle_id,
        shift_start=time(8, 0),
        shift_end=time(17, 0),
        max_hours_day=9.0,
        hours_driven_today=0.0,
        status=DriverStatusEnum.AVAILABLE,
        preferred_zones=[],
    )

    db.add(driver)
    db.commit()
    db.refresh(driver)

    print(f"Driver creat pentru user_id={user_id}")
    return driver


today = date.today()
earliest_date = today + timedelta(days=1)
deadline_date = today + timedelta(days=3)

def get_or_create_order(
    db,
    company_id,
    client_id,
    order_ref: str,
    address_pickup: str,
    pickup_lat: float,
    pickup_lon: float,
    address_delivery: str,
    delivery_lat: float,
    delivery_lon: float,
    kg: float,
    m3: float,
    type_marfa: MarfaTypeEnum,
    priority: PriorityEnum,
    delivery_deadline: date,
):
    order = db.query(Order).filter(Order.order_ref == order_ref).first()

    if order:
        print(f"Comandă existentă: {order_ref}")
        return order

    order = Order(
        company_id=company_id,
        client_id=client_id,
        order_ref=order_ref,

        address_pickup=address_pickup,
        pickup_lat=pickup_lat,
        pickup_lon=pickup_lon,
        pickup_time_window_start=time(8, 0),
        pickup_time_window_end=time(11, 0),

        address_delivery=address_delivery,
        delivery_lat=delivery_lat,
        delivery_lon=delivery_lon,
        delivery_time_window_start=time(12, 0),
        delivery_time_window_end=time(17, 0),

        kg=kg,
        m3=m3,
        type_marfa=type_marfa,
        priority=priority,

        delivery_deadline=delivery_deadline,
        earliest_delivery_date=earliest_date,
        flexibility_days=2,

        status=OrderStatusEnum.PENDING,
        tracking_token=secrets.token_urlsafe(16),
        source=OrderSourceEnum.PORTAL,
        attempts_count=0,
        special_instructions="Date demo pentru testare planning.",
    )

    db.add(order)
    db.commit()
    db.refresh(order)

    print(f"Comandă creată: {order_ref}")
    return order


def seed_demo_data():
    db = SessionLocal()

    try:
        company = get_or_create_company(db)

        manager = get_or_create_user(
            db,
            email="manager.demo@demo-logistics.ro",
            full_name="Manager Demo",
            role=RoleEnum.MANAGER,
            company_id=company.id,
            password="ManagerDemo123",
            phone="0711111111",
            is_approved=True,
        )

        dispecer = get_or_create_user(
            db,
            email="dispecer.demo@demo-logistics.ro",
            full_name="Dispecer Demo",
            role=RoleEnum.DISPECER,
            company_id=company.id,
            password="DispecerDemo123",
            phone="0722222222",
            is_approved=True,
        )

        client = get_or_create_user(
            db,
            email="client.demo@demo-logistics.ro",
            full_name="Client Demo",
            role=RoleEnum.CLIENT,
            company_id=company.id,
            password="ClientDemo123",
            phone="0733333333",
            is_approved=True,
        )

        sofer1 = get_or_create_user(
            db,
            email="sofer1.demo@demo-logistics.ro",
            full_name="Sofer Demo 1",
            role=RoleEnum.SOFER,
            company_id=company.id,
            password="SoferDemo123",
            phone="0744444441",
            is_approved=True,
        )

        sofer2 = get_or_create_user(
            db,
            email="sofer2.demo@demo-logistics.ro",
            full_name="Sofer Demo 2",
            role=RoleEnum.SOFER,
            company_id=company.id,
            password="SoferDemo123",
            phone="0744444442",
            is_approved=True,
        )

        vehicle1 = get_or_create_vehicle(
            db,
            company_id=company.id,
            plate="CJ-10-DEM",
            capacity_kg=1500,
            capacity_m3=10,
            vehicle_type=VehicleTypeEnum.VAN,
            fuel_type=FuelTypeEnum.DIESEL,
            avg_consumption=8.5,
        )

        vehicle2 = get_or_create_vehicle(
            db,
            company_id=company.id,
            plate="CJ-20-DEM",
            capacity_kg=3000,
            capacity_m3=20,
            vehicle_type=VehicleTypeEnum.TRUCK,
            fuel_type=FuelTypeEnum.DIESEL,
            avg_consumption=13.0,
        )

        get_or_create_driver(db, company.id, sofer1.id, vehicle1.id)
        get_or_create_driver(db, company.id, sofer2.id, vehicle2.id)

        get_or_create_order(
            db,
            company_id=company.id,
            client_id=client.id,
            order_ref="DEMO-ORD-001",
            address_pickup="Depozit Cluj-Napoca, Strada Fabricii 10",
            pickup_lat=46.7860,
            pickup_lon=23.6200,
            address_delivery="Piața Unirii 1, Cluj-Napoca",
            delivery_lat=46.7704,
            delivery_lon=23.5896,
            kg=250,
            m3=1.5,
            type_marfa=MarfaTypeEnum.STANDARD,
            priority=PriorityEnum.NORMAL,
            delivery_deadline=deadline_date,
        )

        get_or_create_order(
            db,
            company_id=company.id,
            client_id=client.id,
            order_ref="DEMO-ORD-002",
            address_pickup="Depozit Cluj-Napoca, Strada Fabricii 10",
            pickup_lat=46.7860,
            pickup_lon=23.6200,
            address_delivery="Iulius Mall Cluj-Napoca",
            delivery_lat=46.7712,
            delivery_lon=23.6256,
            kg=400,
            m3=2.0,
            type_marfa=MarfaTypeEnum.FRAGIL,
            priority=PriorityEnum.URGENT,
            delivery_deadline=deadline_date,
        )

        get_or_create_order(
            db,
            company_id=company.id,
            client_id=client.id,
            order_ref="DEMO-ORD-003",
            address_pickup="Depozit Cluj-Napoca, Strada Fabricii 10",
            pickup_lat=46.7860,
            pickup_lon=23.6200,
            address_delivery="Vivo Cluj-Napoca",
            delivery_lat=46.7485,
            delivery_lon=23.5335,
            kg=700,
            m3=3.5,
            type_marfa=MarfaTypeEnum.PERISABIL,
            priority=PriorityEnum.CRITIC,
            delivery_deadline=deadline_date,
        )

        print("\nSeed demo data finalizat cu succes.")
        print("Date login demo:")
        print("Manager:  manager.demo@demo-logistics.ro / ManagerDemo123")
        print("Dispecer: dispecer.demo@demo-logistics.ro / DispecerDemo123")
        print("Client:   client.demo@demo-logistics.ro / ClientDemo123")
        print("Soferi:   sofer1.demo@demo-logistics.ro / SoferDemo123")
        print("         sofer2.demo@demo-logistics.ro / SoferDemo123")

    finally:
        db.close()


if __name__ == "__main__":
    seed_demo_data()