from app.routers import (
    admin,
    analytics,
    auth,
    companies,
    dashboard,
    drivers,
    incidents,
    orders,
    planning,
    system_config,
    trips,
    vehicles,
)
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="TMS Platform",
    description="Transportation Management System - Disertatie SIA 2025",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200", "http://127.0.0.1:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(companies.router)
app.include_router(dashboard.router)
app.include_router(vehicles.router)
app.include_router(drivers.router)
app.include_router(incidents.router)
app.include_router(orders.router)
app.include_router(planning.router)
app.include_router(trips.router)
app.include_router(system_config.router)
app.include_router(analytics.router)


@app.get("/")
def root():
    return {"message": "TMS Platform API is running"}


@app.get("/health")
def health():
    return {"status": "ok"}
