import { ChangeDetectorRef, Component, Inject, OnDestroy, OnInit } from '@angular/core';
import { CommonModule, DOCUMENT } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { forkJoin } from 'rxjs';

import { TranslatePipe } from '../../core/pipes/translate';
import { AdminService } from '../../core/services/admin';
import { DriverService } from '../../core/services/driver';
import {
  EligibleOrderSummary,
  EligibleOrdersResponse,
  PlanningService,
  StrategyComparisonResponse,
  StrategyComparisonVariant,
  StrategyTripPreview,
} from '../../core/services/planning';
import { TripResponse, TripService, TripStopResponse } from '../../core/services/trip';
import { VehicleService } from '../../core/services/vehicle';

interface PlanningCard {
  title: string;
  value: string;
  detail: string;
}

interface TripAssignmentOption {
  value: string;
  label: string;
}

@Component({
  selector: 'app-planning',
  imports: [CommonModule, TranslatePipe],
  templateUrl: './planning.html',
  styleUrl: './planning.scss',
})
export class Planning implements OnInit, OnDestroy {
  isLoadingEligibleOrders = false;
  isLoadingProposedTrips = false;
  isComparingStrategies = false;
  isGeneratingPlan = false;
  isLoadingTripStops = false;
  isSavingTripEdits = false;
  approvingTripId: string | null = null;
  eligibleOrdersError = '';
  proposedTripsError = '';
  approveTripError = '';
  approveTripSuccess = '';
  editTripError = '';
  editTripSuccess = '';
  compareStrategiesError = '';
  planGenerationSuccess = '';
  eligibleOrdersResponse: EligibleOrdersResponse | null = null;
  proposedTrips: TripResponse[] = [];
  driverLabels = new Map<string, string>();
  vehicleLabels = new Map<string, string>();
  driverOptions: TripAssignmentOption[] = [];
  vehicleOptions: TripAssignmentOption[] = [];
  selectedEditTrip: TripResponse | null = null;
  selectedEditTripStops: TripStopResponse[] = [];
  editTripDriverId = '';
  editTripVehicleId = '';
  strategyComparison: StrategyComparisonResponse | null = null;
  readonly today = this.toDateInputValue(new Date());
  dateStart = this.today;
  dateEnd = this.toDateInputValue(this.addDays(new Date(), 2));

  constructor(
    private planningService: PlanningService,
    private tripService: TripService,
    private adminService: AdminService,
    private driverService: DriverService,
    private vehicleService: VehicleService,
    private changeDetectorRef: ChangeDetectorRef,
    @Inject(DOCUMENT) private document: Document,
  ) {}

  ngOnInit(): void {
    this.loadTripLabels();
    this.loadEligibleOrders();
    this.loadProposedTrips();
  }

  ngOnDestroy(): void {
    this.unlockBackgroundScroll();
  }

  get cards(): PlanningCard[] {
    const response = this.eligibleOrdersResponse;
    const byPriority = response?.by_priority ?? {};
    const priorityCount =
      (byPriority['CRITIC'] ?? 0) + (byPriority['URGENT'] ?? 0);

    return [
      {
        title: 'planning.metric.eligible_orders',
        value: String(response?.total_eligible ?? 0),
        detail: 'planning.metric.eligible_orders_detail',
      },
      {
        title: 'planning.metric.total_weight',
        value: `${response?.total_kg ?? 0} kg`,
        detail: 'planning.metric.total_weight_detail',
      },
      {
        title: 'planning.metric.total_volume',
        value: `${response?.total_m3 ?? 0} m3`,
        detail: 'planning.metric.total_volume_detail',
      },
      {
        title: 'planning.metric.priority_orders',
        value: String(priorityCount),
        detail: 'planning.metric.priority_orders_detail',
      },
    ];
  }

  get planningQueue(): EligibleOrderSummary[] {
    return this.eligibleOrdersResponse?.orders ?? [];
  }

  loadTripLabels(): void {
    forkJoin({
      employees: this.adminService.listEmployees(),
      drivers: this.driverService.listDrivers(),
      vehicles: this.vehicleService.listVehicles(),
    }).subscribe({
      next: ({ employees, drivers, vehicles }) => {
        const employeesById = new Map(employees.map((employee) => [employee.id, employee]));

        this.driverLabels = new Map(
          drivers.map((driver) => {
            const employee = employeesById.get(driver.user_id);
            return [driver.id, employee?.full_name || employee?.email || driver.id];
          }),
        );
        this.vehicleLabels = new Map(vehicles.map((vehicle) => [vehicle.id, vehicle.plate]));
        this.driverOptions = drivers.map((driver) => ({
          value: driver.id,
          label: this.driverLabels.get(driver.id) ?? driver.id,
        }));
        this.vehicleOptions = vehicles.map((vehicle) => ({
          value: vehicle.id,
          label: vehicle.plate,
        }));
        this.changeDetectorRef.detectChanges();
      },
      error: () => {
        this.driverLabels = new Map();
        this.vehicleLabels = new Map();
        this.driverOptions = [];
        this.vehicleOptions = [];
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  getDriverLabel(driverId: string | null): string {
    return driverId ? this.driverLabels.get(driverId) ?? driverId : 'vehicles.not_available';
  }

  getVehicleLabel(vehicleId: string | null): string {
    return vehicleId ? this.vehicleLabels.get(vehicleId) ?? vehicleId : 'vehicles.not_available';
  }

  loadProposedTrips(): void {
    this.isLoadingProposedTrips = true;
    this.proposedTripsError = '';
    this.approveTripError = '';
    this.changeDetectorRef.detectChanges();

    this.tripService.listTrips('PROPOSED').subscribe({
      next: (trips) => {
        this.proposedTrips = trips;
        this.isLoadingProposedTrips = false;
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isLoadingProposedTrips = false;
        this.proposedTripsError = error.error?.detail ?? 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  approveTrip(trip: TripResponse): void {
    this.approvingTripId = trip.id;
    this.approveTripError = '';
    this.approveTripSuccess = '';
    this.changeDetectorRef.detectChanges();

    this.tripService.approveTrip(trip.id).subscribe({
      next: () => {
        this.approvingTripId = null;
        this.approveTripSuccess = 'planning.trip_approve_success';
        this.proposedTrips = this.proposedTrips.filter((currentTrip) => currentTrip.id !== trip.id);
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.approvingTripId = null;
        this.approveTripError = error.error?.detail ?? 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  openEditTrip(trip: TripResponse): void {
    this.selectedEditTrip = trip;
    this.editTripDriverId = trip.driver_id ?? '';
    this.editTripVehicleId = trip.vehicle_id ?? '';
    this.selectedEditTripStops = [];
    this.editTripError = '';
    this.editTripSuccess = '';
    this.isLoadingTripStops = true;
    this.lockBackgroundScroll();
    this.changeDetectorRef.detectChanges();

    this.tripService.listTripStops(trip.id).subscribe({
      next: (stops) => {
        this.selectedEditTripStops = stops;
        this.isLoadingTripStops = false;
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isLoadingTripStops = false;
        this.editTripError = error.error?.detail ?? 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  closeEditTrip(): void {
    this.selectedEditTrip = null;
    this.selectedEditTripStops = [];
    this.editTripDriverId = '';
    this.editTripVehicleId = '';
    this.editTripError = '';
    this.editTripSuccess = '';
    this.isLoadingTripStops = false;
    this.unlockBackgroundScroll();
    this.changeDetectorRef.detectChanges();
  }

  updateEditTripDriver(value: string): void {
    this.editTripDriverId = value;
    this.editTripError = '';
    this.editTripSuccess = '';
    this.changeDetectorRef.detectChanges();
  }

  updateEditTripVehicle(value: string): void {
    this.editTripVehicleId = value;
    this.editTripError = '';
    this.editTripSuccess = '';
    this.changeDetectorRef.detectChanges();
  }

  hasTripEditChanges(): boolean {
    return Boolean(
      this.selectedEditTrip &&
      (
        this.editTripDriverId !== (this.selectedEditTrip.driver_id ?? '') ||
        this.editTripVehicleId !== (this.selectedEditTrip.vehicle_id ?? '')
      ),
    );
  }

  saveTripEdits(): void {
    const trip = this.selectedEditTrip;

    if (!trip || !this.hasTripEditChanges()) {
      return;
    }

    const requests = [];

    if (this.editTripDriverId && this.editTripDriverId !== (trip.driver_id ?? '')) {
      requests.push(this.planningService.changeTripDriver(trip.id, this.editTripDriverId));
    }

    if (this.editTripVehicleId && this.editTripVehicleId !== (trip.vehicle_id ?? '')) {
      requests.push(this.planningService.changeTripVehicle(trip.id, this.editTripVehicleId));
    }

    if (!requests.length) {
      return;
    }

    this.isSavingTripEdits = true;
    this.editTripError = '';
    this.editTripSuccess = '';
    this.changeDetectorRef.detectChanges();

    forkJoin(requests).subscribe({
      next: () => {
        const updatedTrip = {
          ...trip,
          driver_id: this.editTripDriverId || null,
          vehicle_id: this.editTripVehicleId || null,
        };

        this.selectedEditTrip = updatedTrip;
        this.proposedTrips = this.proposedTrips.map((currentTrip) =>
          currentTrip.id === updatedTrip.id ? updatedTrip : currentTrip,
        );
        this.isSavingTripEdits = false;
        this.editTripSuccess = 'planning.trip_update_success';
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isSavingTripEdits = false;
        this.editTripError = error.error?.detail ?? 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  loadEligibleOrders(): void {
    this.isLoadingEligibleOrders = true;
    this.eligibleOrdersError = '';
    this.changeDetectorRef.detectChanges();

    this.planningService
      .getEligibleOrders({
        date_start: this.dateStart,
        date_end: this.dateEnd,
      })
      .subscribe({
        next: (response) => {
          this.eligibleOrdersResponse = response;
          this.isLoadingEligibleOrders = false;
          this.changeDetectorRef.detectChanges();
        },
        error: (error: HttpErrorResponse) => {
          this.isLoadingEligibleOrders = false;
          this.eligibleOrdersError = error.error?.detail ?? 'common.error_generic';
          this.changeDetectorRef.detectChanges();
        },
      });
  }

  updateDateStart(value: string): void {
    this.dateStart = value;
    this.strategyComparison = null;
    this.planGenerationSuccess = '';
    this.unlockBackgroundScroll();
    this.changeDetectorRef.detectChanges();
  }

  updateDateEnd(value: string): void {
    this.dateEnd = value;
    this.strategyComparison = null;
    this.planGenerationSuccess = '';
    this.unlockBackgroundScroll();
    this.changeDetectorRef.detectChanges();
  }

  applyPlanningInterval(): void {
    this.eligibleOrdersError = '';
    this.strategyComparison = null;
    this.planGenerationSuccess = '';

    const intervalError = this.getPlanningIntervalError();
    if (intervalError) {
      this.eligibleOrdersError = intervalError;
      this.changeDetectorRef.detectChanges();
      return;
    }

    this.loadEligibleOrders();
  }

  compareStrategies(): void {
    this.compareStrategiesError = '';
    this.strategyComparison = null;
    this.planGenerationSuccess = '';

    const intervalError = this.getPlanningIntervalError();
    if (intervalError) {
      this.compareStrategiesError = intervalError;
      this.changeDetectorRef.detectChanges();
      return;
    }

    this.isComparingStrategies = true;
    this.changeDetectorRef.detectChanges();

    this.planningService
      .compareStrategies({
        date_start: this.dateStart,
        date_end: this.dateEnd,
      })
      .subscribe({
        next: (comparison) => {
          this.strategyComparison = comparison;
          this.isGeneratingPlan = false;
          this.isComparingStrategies = false;
          this.lockBackgroundScroll();
          this.changeDetectorRef.detectChanges();
        },
        error: (error: HttpErrorResponse) => {
          this.isComparingStrategies = false;
          this.compareStrategiesError = error.error?.detail ?? 'common.error_generic';
          this.changeDetectorRef.detectChanges();
        },
      });
  }

  closeStrategyComparison(): void {
    this.strategyComparison = null;
    this.isGeneratingPlan = false;
    this.unlockBackgroundScroll();
    this.changeDetectorRef.detectChanges();
  }

  canGeneratePlan(variant: StrategyComparisonVariant): boolean {
    return Boolean(variant.strategy && !variant.error && !this.isComparingStrategies && !this.isGeneratingPlan);
  }

  generatePlan(variant: StrategyComparisonVariant): void {
    if (!this.canGeneratePlan(variant)) {
      return;
    }

    this.compareStrategiesError = '';
    this.planGenerationSuccess = '';
    this.isGeneratingPlan = true;
    this.changeDetectorRef.detectChanges();

    this.planningService
      .generatePlanWithStrategy({
        date_start: this.dateStart,
        date_end: this.dateEnd,
        strategy: variant.strategy,
      })
      .subscribe({
        next: () => {
          this.strategyComparison = null;
          this.isGeneratingPlan = false;
          this.planGenerationSuccess = 'planning.compare.generate_success';
          this.unlockBackgroundScroll();
          this.loadEligibleOrders();
          this.loadProposedTrips();
          this.changeDetectorRef.detectChanges();
        },
        error: (error: HttpErrorResponse) => {
          this.isGeneratingPlan = false;
          this.compareStrategiesError = error.error?.detail ?? 'common.error_generic';
          this.changeDetectorRef.detectChanges();
        },
      });
  }

  getPriorityKey(priority: string): string {
    return `orders.priority.${priority.toLowerCase()}`;
  }

  getCargoTypeKey(cargoType: string): string {
    const cargoTypeMap: Record<string, string> = {
      STANDARD: 'orders.cargo.standard',
      FRAGIL: 'orders.cargo.fragile',
      PERISABIL: 'orders.cargo.perishable',
      ADR: 'orders.cargo.adr',
    };

    return cargoTypeMap[cargoType] ?? cargoType;
  }

  getStrategyKey(strategy: string): string {
    const strategyMap: Record<string, string> = {
      GREEDY_DEADLINE: 'planning.strategy.greedy_deadline',
      MAX_DENSITY: 'planning.strategy.max_density',
      HYBRID: 'planning.strategy.hybrid',
    };

    return strategyMap[strategy] ?? strategy;
  }

  getTripOrders(trip: StrategyTripPreview): string[] {
    const orderRefs = new Set<string>();

    (trip.stops ?? []).forEach((stop) => {
      if (stop.order_ref) {
        orderRefs.add(stop.order_ref);
      }
    });

    return [...orderRefs];
  }


  hasTrips(variant: StrategyComparisonVariant): boolean {
    return Boolean(variant.trips?.length);
  }

  getStrategyWarnings(variant: StrategyComparisonVariant): string[] {
    return (variant.warnings ?? []).map((warning) => {
      const message = warning.message ?? warning.reason ?? '';

      if (warning.order_ref && message) {
        return `${warning.order_ref}: ${message}`;
      }

      return message || warning.order_ref || 'planning.compare.warning';
    });
  }

  private getPlanningIntervalError(): string {
    if (!this.dateStart || !this.dateEnd) {
      return 'planning.interval_required';
    }

    if (this.dateEnd < this.dateStart) {
      return 'planning.interval_invalid';
    }

    return '';
  }

  private addDays(date: Date, days: number): Date {
    const nextDate = new Date(date);
    nextDate.setDate(nextDate.getDate() + days);
    return nextDate;
  }

  private toDateInputValue(date: Date): string {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  private lockBackgroundScroll(): void {
    this.document.body.classList.add('modal-scroll-lock');
  }

  private unlockBackgroundScroll(): void {
    this.document.body.classList.remove('modal-scroll-lock');
  }
}
