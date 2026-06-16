import { ChangeDetectorRef, Component, Inject, OnDestroy, OnInit } from '@angular/core';
import { CommonModule, DOCUMENT } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { TranslatePipe } from '../../core/pipes/translate';
import { AdminService, UserResponse } from '../../core/services/admin';
import {
  CreateDriverRequest,
  DriverResponse,
  DriverService,
  UpdateDriverRequest,
} from '../../core/services/driver';
import { VehicleResponse, VehicleService } from '../../core/services/vehicle';

interface Driver {
  id: string;
  userId: string;
  companyId?: string;
  vehicleId?: string | null;
  name?: string;
  phone?: string;
  email?: string;
  vehiclePlate?: string;
  statusKey: string;
  license?: string;
  activeTrip?: string;
  shiftStart?: string | null;
  shiftEnd?: string | null;
  maxHoursDay?: number;
  hoursDrivenToday?: number;
}

@Component({
  selector: 'app-drivers',
  imports: [CommonModule, ReactiveFormsModule, TranslatePipe],
  templateUrl: './drivers.html',
  styleUrl: './drivers.scss',
})
export class Drivers implements OnInit, OnDestroy {
  isAddDriverOpen = false;
  isLoadingDrivers = false;
  loadDriversError = '';
  isCreatingDriver = false;
  createDriverSuccess = '';
  createDriverError = '';
  selectedEditDriver: Driver | null = null;
  isUpdatingDriver = false;
  updateDriverSuccess = '';
  updateDriverError = '';
  isLoadingEditVehicles = false;
  editDriverOptionsError = '';
  isLoadingDriverOptions = false;
  driverOptionsError = '';
  selectableDrivers: UserResponse[] = [];
  selectableVehicles: VehicleResponse[] = [];
  driverSearchTerm = '';
  vehicleSearchTerm = '';
  editVehicleSearchTerm = '';

  driverForm;
  editDriverForm;

  constructor(
    private fb: FormBuilder,
    private adminService: AdminService,
    private driverService: DriverService,
    private vehicleService: VehicleService,
    private changeDetectorRef: ChangeDetectorRef,
    @Inject(DOCUMENT) private document: Document,
  ) {
    this.driverForm = this.fb.group({
      user_id: ['', [Validators.required]],
      vehicle_id: [''],
      shift_start: [''],
      shift_end: [''],
      max_hours_day: [9, [Validators.required, Validators.min(1)]],
    });
    this.editDriverForm = this.fb.group({
      vehicle_id: [''],
      shift_start: [''],
      shift_end: [''],
      max_hours_day: [9, [Validators.required, Validators.min(1)]],
      status: ['AVAILABLE', [Validators.required]],
    });
  }

  drivers: Driver[] = [];

  ngOnInit(): void {
    this.loadDrivers();
  }

  ngOnDestroy(): void {
    this.unlockBackgroundScroll();
  }

  loadDrivers(): void {
    this.isLoadingDrivers = true;
    this.loadDriversError = '';
    this.changeDetectorRef.detectChanges();

    forkJoin({
      driverProfiles: this.driverService.listDrivers(),
      employees: this.adminService.listEmployees(),
      vehicles: this.vehicleService.listVehicles(),
    }).subscribe({
      next: ({ driverProfiles, employees, vehicles }) => {
        this.drivers = driverProfiles.map((driver) =>
          this.mapDriverResponse(
            driver,
            employees.find((employee) => employee.id === driver.user_id),
            vehicles.find((vehicle) => vehicle.id === driver.vehicle_id),
          ),
        );
        this.isLoadingDrivers = false;
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isLoadingDrivers = false;

        if (error.error?.detail) {
          this.loadDriversError = error.error.detail;
          this.changeDetectorRef.detectChanges();
          return;
        }

        this.loadDriversError = 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  get filteredSelectableDrivers(): UserResponse[] {
    const query = this.driverSearchTerm.trim().toLowerCase();

    if (!query) {
      return this.selectableDrivers;
    }

    return this.selectableDrivers.filter((driver) =>
      [driver.id, driver.full_name, driver.email, driver.phone ?? '']
        .join(' ')
        .toLowerCase()
        .includes(query),
    );
  }

  get filteredSelectableVehicles(): VehicleResponse[] {
    const query = this.vehicleSearchTerm.trim().toLowerCase();

    if (!query) {
      return this.selectableVehicles;
    }

    return this.selectableVehicles.filter((vehicle) =>
      [
        vehicle.id,
        vehicle.plate,
        vehicle.type,
        vehicle.status,
        vehicle.fuel_type,
        vehicle.capacity_kg,
        vehicle.capacity_m3,
      ]
        .join(' ')
        .toLowerCase()
        .includes(query),
    );
  }

  get selectedDriver(): UserResponse | undefined {
    const selectedDriverId = this.driverForm.get('user_id')?.value;
    return this.selectableDrivers.find((driver) => driver.id === selectedDriverId);
  }

  get selectedVehicle(): VehicleResponse | undefined {
    const selectedVehicleId = this.driverForm.get('vehicle_id')?.value;
    return this.selectableVehicles.find((vehicle) => vehicle.id === selectedVehicleId);
  }

  get filteredEditSelectableVehicles(): VehicleResponse[] {
    const query = this.editVehicleSearchTerm.trim().toLowerCase();

    if (!query) {
      return this.selectableVehicles;
    }

    return this.selectableVehicles.filter((vehicle) =>
      [
        vehicle.id,
        vehicle.plate,
        vehicle.type,
        vehicle.status,
        vehicle.fuel_type,
        vehicle.capacity_kg,
        vehicle.capacity_m3,
      ]
        .join(' ')
        .toLowerCase()
        .includes(query),
    );
  }

  get selectedEditVehicle(): VehicleResponse | undefined {
    const selectedVehicleId = this.editDriverForm.get('vehicle_id')?.value;
    return this.selectableVehicles.find((vehicle) => vehicle.id === selectedVehicleId);
  }

  openAddDriver(): void {
    this.isAddDriverOpen = true;
    this.selectedEditDriver = null;
    this.createDriverSuccess = '';
    this.createDriverError = '';
    this.updateDriverSuccess = '';
    this.updateDriverError = '';
    this.loadDriverOptions();
  }

  closeAddDriver(): void {
    this.isAddDriverOpen = false;
    this.createDriverError = '';
    this.driverForm.reset({
      user_id: '',
      vehicle_id: '',
      shift_start: '',
      shift_end: '',
      max_hours_day: 9,
    });
    this.driverSearchTerm = '';
    this.vehicleSearchTerm = '';
  }

  loadDriverOptions(): void {
    this.isLoadingDriverOptions = true;
    this.driverOptionsError = '';
    this.changeDetectorRef.detectChanges();

    forkJoin({
      employees: this.adminService.listEmployees(),
      vehicles: this.vehicleService.listVehicles(),
      driverProfiles: this.driverService.listDrivers(),
    }).subscribe({
      next: ({ employees, vehicles, driverProfiles }) => {
        const existingDriverUserIds = new Set(driverProfiles.map((driver) => driver.user_id));

        this.selectableDrivers = employees.filter(
          (employee) =>
            employee.role === 'SOFER' && employee.is_active && !existingDriverUserIds.has(employee.id),
        );
        this.selectableVehicles = vehicles;
        this.isLoadingDriverOptions = false;
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isLoadingDriverOptions = false;

        if (error.error?.detail) {
          this.driverOptionsError = error.error.detail;
          this.changeDetectorRef.detectChanges();
          return;
        }

        this.driverOptionsError = 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  updateDriverSearch(value: string): void {
    this.driverSearchTerm = value;
  }

  updateVehicleSearch(value: string): void {
    this.vehicleSearchTerm = value;
  }

  selectDriver(driver: UserResponse): void {
    this.driverForm.patchValue({ user_id: driver.id });
    this.driverForm.get('user_id')?.markAsTouched();
  }

  selectVehicle(vehicle: VehicleResponse): void {
    this.driverForm.patchValue({ vehicle_id: vehicle.id });
  }

  clearVehicleSelection(): void {
    this.driverForm.patchValue({ vehicle_id: '' });
  }

  openEditDriver(driver: Driver): void {
    this.selectedEditDriver = driver;
    this.isAddDriverOpen = false;
    this.lockBackgroundScroll();
    this.createDriverSuccess = '';
    this.createDriverError = '';
    this.updateDriverSuccess = '';
    this.updateDriverError = '';
    this.editDriverOptionsError = '';
    this.editVehicleSearchTerm = '';
    this.editDriverForm.reset({
      vehicle_id: driver.vehicleId || '',
      shift_start: driver.shiftStart || '',
      shift_end: driver.shiftEnd || '',
      max_hours_day: driver.maxHoursDay ?? 9,
      status: this.statusFromKey(driver.statusKey),
    });
    this.loadEditVehicles();
  }

  closeEditDriver(): void {
    this.selectedEditDriver = null;
    this.unlockBackgroundScroll();
    this.updateDriverError = '';
    this.editDriverOptionsError = '';
    this.editVehicleSearchTerm = '';
    this.editDriverForm.reset({
      vehicle_id: '',
      shift_start: '',
      shift_end: '',
      max_hours_day: 9,
      status: 'AVAILABLE',
    });
  }

  loadEditVehicles(): void {
    this.isLoadingEditVehicles = true;
    this.editDriverOptionsError = '';
    this.changeDetectorRef.detectChanges();

    this.vehicleService.listVehicles().subscribe({
      next: (vehicles) => {
        this.selectableVehicles = vehicles;
        this.isLoadingEditVehicles = false;
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isLoadingEditVehicles = false;

        if (error.error?.detail) {
          this.editDriverOptionsError = error.error.detail;
          this.changeDetectorRef.detectChanges();
          return;
        }

        this.editDriverOptionsError = 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  updateEditVehicleSearch(value: string): void {
    this.editVehicleSearchTerm = value;
  }

  selectEditVehicle(vehicle: VehicleResponse): void {
    this.editDriverForm.patchValue({ vehicle_id: vehicle.id });
  }

  clearEditVehicleSelection(): void {
    this.editDriverForm.patchValue({ vehicle_id: '' });
  }

  vehicleTypeKey(type: string): string {
    return `vehicles.type.${type.toLowerCase()}`;
  }

  vehicleStatusKey(status: string): string {
    return `vehicles.status.${status.toLowerCase()}`;
  }

  fuelTypeKey(fuelType: string): string {
    return `vehicles.fuel.${fuelType.toLowerCase()}`;
  }

  createDriver(): void {
    this.createDriverSuccess = '';
    this.createDriverError = '';

    if (this.driverForm.invalid) {
      this.driverForm.markAllAsTouched();
      return;
    }

    const formValue = this.driverForm.value;
    const payload: CreateDriverRequest = {
      user_id: formValue.user_id ?? '',
      vehicle_id: formValue.vehicle_id || null,
      shift_start: formValue.shift_start || null,
      shift_end: formValue.shift_end || null,
      max_hours_day: formValue.max_hours_day ?? 9,
    };

    this.isCreatingDriver = true;
    this.changeDetectorRef.detectChanges();

    this.driverService.createDriver(payload).subscribe({
      next: (driver) => {
        this.isCreatingDriver = false;
        this.drivers = [this.mapDriverResponse(driver, this.selectedDriver, this.selectedVehicle), ...this.drivers];
        this.selectableDrivers = this.selectableDrivers.filter(
          (selectableDriver) => selectableDriver.id !== driver.user_id,
        );
        this.closeAddDriver();
        this.createDriverSuccess = 'drivers.create_success';
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isCreatingDriver = false;

        if (error.error?.detail) {
          this.createDriverError = error.error.detail;
          this.changeDetectorRef.detectChanges();
          return;
        }

        this.createDriverError = 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  updateDriver(): void {
    this.updateDriverSuccess = '';
    this.updateDriverError = '';

    if (!this.selectedEditDriver) {
      return;
    }

    if (this.editDriverForm.invalid) {
      this.editDriverForm.markAllAsTouched();
      return;
    }

    const formValue = this.editDriverForm.value;
    const payload: UpdateDriverRequest = {
      vehicle_id: formValue.vehicle_id || null,
      shift_start: formValue.shift_start || null,
      shift_end: formValue.shift_end || null,
      max_hours_day: formValue.max_hours_day ?? 9,
      status: formValue.status ?? 'AVAILABLE',
    };
    const existingDriver = this.selectedEditDriver;
    const selectedVehicle = this.selectedEditVehicle;

    this.isUpdatingDriver = true;
    this.changeDetectorRef.detectChanges();

    this.driverService.updateDriver(existingDriver.id, payload).subscribe({
      next: (driver) => {
        this.isUpdatingDriver = false;
        const updatedDriver = this.mapDriverResponse(
          driver,
          this.driverToUserResponse(existingDriver),
          selectedVehicle,
        );

        this.drivers = this.drivers.map((currentDriver) =>
          currentDriver.id === updatedDriver.id ? updatedDriver : currentDriver,
        );
        this.closeEditDriver();
        this.updateDriverSuccess = 'drivers.update_success';
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isUpdatingDriver = false;

        if (error.error?.detail) {
          this.updateDriverError = error.error.detail;
          this.changeDetectorRef.detectChanges();
          return;
        }

        this.updateDriverError = 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  private mapDriverResponse(
    driver: DriverResponse,
    user?: UserResponse,
    vehicle?: VehicleResponse,
  ): Driver {
    return {
      id: driver.id,
      userId: driver.user_id,
      companyId: driver.company_id,
      vehicleId: driver.vehicle_id,
      name: user?.full_name,
      phone: user?.phone ?? undefined,
      email: user?.email,
      vehiclePlate: vehicle?.plate,
      shiftStart: driver.shift_start,
      shiftEnd: driver.shift_end,
      maxHoursDay: driver.max_hours_day,
      hoursDrivenToday: driver.hours_driven_today,
      statusKey: `drivers.status.${driver.status.toLowerCase()}`,
    };
  }

  private statusFromKey(statusKey: string): string {
    return statusKey.replace('drivers.status.', '').toUpperCase();
  }

  private driverToUserResponse(driver: Driver): UserResponse {
    return {
      id: driver.userId,
      company_id: driver.companyId ?? null,
      email: driver.email ?? '',
      full_name: driver.name ?? driver.userId,
      role: 'SOFER',
      is_active: true,
      is_approved: true,
      must_change_password: false,
      phone: driver.phone ?? null,
    };
  }

  private lockBackgroundScroll(): void {
    this.document.body.classList.add('modal-scroll-lock');
  }

  private unlockBackgroundScroll(): void {
    this.document.body.classList.remove('modal-scroll-lock');
  }
}
