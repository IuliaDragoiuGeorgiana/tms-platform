import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';

import { TranslatePipe } from '../../core/pipes/translate';
import {
  CreateVehicleRequest,
  UpdateVehicleRequest,
  VehicleResponse,
  VehicleService,
} from '../../core/services/vehicle';

@Component({
  selector: 'app-vehicles',
  imports: [CommonModule, ReactiveFormsModule, TranslatePipe],
  templateUrl: './vehicles.html',
  styleUrl: './vehicles.scss',
})
export class Vehicles implements OnInit {
  vehicles: VehicleResponse[] = [];
  searchTerm = '';
  showOnlyAvailable = false;
  isLoadingVehicles = false;
  loadVehiclesError = '';
  isAddVehicleOpen = false;
  isCreatingVehicle = false;
  createVehicleSuccess = '';
  createVehicleError = '';
  selectedEditVehicle: VehicleResponse | null = null;
  isUpdatingVehicle = false;
  updateVehicleSuccess = '';
  updateVehicleError = '';

  vehicleForm;

  constructor(
    private fb: FormBuilder,
    private vehicleService: VehicleService,
    private changeDetectorRef: ChangeDetectorRef,
  ) {
    this.vehicleForm = this.fb.group({
      plate: ['', [Validators.required]],
      capacity_kg: [null as number | null, [Validators.required, Validators.min(1)]],
      capacity_m3: [null as number | null, [Validators.required, Validators.min(0.1)]],
      type: ['VAN', [Validators.required]],
      status: ['DISPONIBIL', [Validators.required]],
      fuel_type: ['DIESEL', [Validators.required]],
      avg_consumption: [null as number | null, [Validators.min(0)]],
      itp_expiry: [''],
    });
  }

  ngOnInit(): void {
    this.loadVehicles();
  }

  get filteredVehicles(): VehicleResponse[] {
    const visibleVehicles = this.showOnlyAvailable
      ? this.vehicles.filter((vehicle) => vehicle.status === 'DISPONIBIL')
      : this.vehicles;
    const query = this.searchTerm.trim().toLowerCase();

    if (!query) {
      return visibleVehicles;
    }

    return visibleVehicles.filter((vehicle) =>
      [
        vehicle.id,
        vehicle.plate,
        vehicle.type,
        vehicle.status,
        vehicle.fuel_type,
        vehicle.capacity_kg,
        vehicle.capacity_m3,
        vehicle.avg_consumption ?? '',
        vehicle.itp_expiry ?? '',
      ]
        .join(' ')
        .toLowerCase()
        .includes(query),
    );
  }

  loadVehicles(): void {
    this.isLoadingVehicles = true;
    this.loadVehiclesError = '';
    this.changeDetectorRef.detectChanges();

    this.vehicleService.listVehicles().subscribe({
      next: (vehicles) => {
        this.vehicles = vehicles;
        this.isLoadingVehicles = false;
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isLoadingVehicles = false;

        if (error.error?.detail) {
          this.loadVehiclesError = error.error.detail;
          this.changeDetectorRef.detectChanges();
          return;
        }

        this.loadVehiclesError = 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  updateSearch(value: string): void {
    this.searchTerm = value;
  }

  updateAvailableFilter(value: boolean): void {
    this.showOnlyAvailable = value;
  }

  openAddVehicle(): void {
    this.isAddVehicleOpen = true;
    this.selectedEditVehicle = null;
    this.createVehicleSuccess = '';
    this.createVehicleError = '';
    this.updateVehicleSuccess = '';
    this.updateVehicleError = '';
  }

  closeAddVehicle(): void {
    this.isAddVehicleOpen = false;
    this.createVehicleError = '';
    this.resetVehicleForm();
  }

  createVehicle(): void {
    this.createVehicleSuccess = '';
    this.createVehicleError = '';

    if (this.vehicleForm.invalid) {
      this.vehicleForm.markAllAsTouched();
      return;
    }

    const formValue = this.vehicleForm.value;
    const payload: CreateVehicleRequest = {
      plate: formValue.plate ?? '',
      capacity_kg: Number(formValue.capacity_kg),
      capacity_m3: Number(formValue.capacity_m3),
      type: formValue.type ?? 'VAN',
      fuel_type: formValue.fuel_type ?? 'DIESEL',
      avg_consumption:
        formValue.avg_consumption === null || formValue.avg_consumption === undefined
          ? null
          : Number(formValue.avg_consumption),
      itp_expiry: formValue.itp_expiry || null,
    };

    this.isCreatingVehicle = true;
    this.changeDetectorRef.detectChanges();

    this.vehicleService.createVehicle(payload).subscribe({
      next: (vehicle) => {
        this.isCreatingVehicle = false;
        this.vehicles = [vehicle, ...this.vehicles];
        this.closeAddVehicle();
        this.createVehicleSuccess = 'vehicles.create_success';
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isCreatingVehicle = false;

        if (error.error?.detail) {
          this.createVehicleError = error.error.detail;
          this.changeDetectorRef.detectChanges();
          return;
        }

        this.createVehicleError = 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  openEditVehicle(vehicle: VehicleResponse): void {
    this.selectedEditVehicle = vehicle;
    this.isAddVehicleOpen = false;
    this.createVehicleSuccess = '';
    this.createVehicleError = '';
    this.updateVehicleSuccess = '';
    this.updateVehicleError = '';
    this.vehicleForm.reset({
      plate: vehicle.plate,
      capacity_kg: vehicle.capacity_kg,
      capacity_m3: vehicle.capacity_m3,
      type: vehicle.type,
      status: vehicle.status,
      fuel_type: vehicle.fuel_type,
      avg_consumption: vehicle.avg_consumption,
      itp_expiry: vehicle.itp_expiry || '',
    });
  }

  closeEditVehicle(): void {
    this.selectedEditVehicle = null;
    this.updateVehicleError = '';
    this.resetVehicleForm();
  }

  updateVehicle(): void {
    this.updateVehicleSuccess = '';
    this.updateVehicleError = '';

    if (!this.selectedEditVehicle) {
      return;
    }

    if (this.vehicleForm.invalid) {
      this.vehicleForm.markAllAsTouched();
      return;
    }

    const formValue = this.vehicleForm.value;
    const payload: UpdateVehicleRequest = {
      plate: formValue.plate ?? '',
      capacity_kg: Number(formValue.capacity_kg),
      capacity_m3: Number(formValue.capacity_m3),
      type: formValue.type ?? 'VAN',
      status: formValue.status ?? 'DISPONIBIL',
      fuel_type: formValue.fuel_type ?? 'DIESEL',
      avg_consumption:
        formValue.avg_consumption === null || formValue.avg_consumption === undefined
          ? null
          : Number(formValue.avg_consumption),
      itp_expiry: formValue.itp_expiry || null,
    };

    this.isUpdatingVehicle = true;
    this.changeDetectorRef.detectChanges();

    this.vehicleService.updateVehicle(this.selectedEditVehicle.id, payload).subscribe({
      next: (vehicle) => {
        this.isUpdatingVehicle = false;
        this.vehicles = this.vehicles.map((existingVehicle) =>
          existingVehicle.id === vehicle.id ? vehicle : existingVehicle,
        );
        this.closeEditVehicle();
        this.updateVehicleSuccess = 'vehicles.update_success';
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isUpdatingVehicle = false;

        if (error.error?.detail) {
          this.updateVehicleError = error.error.detail;
          this.changeDetectorRef.detectChanges();
          return;
        }

        this.updateVehicleError = 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
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

  private resetVehicleForm(): void {
    this.vehicleForm.reset({
      plate: '',
      capacity_kg: null,
      capacity_m3: null,
      type: 'VAN',
      status: 'DISPONIBIL',
      fuel_type: 'DIESEL',
      avg_consumption: null,
      itp_expiry: '',
    });
  }
}
