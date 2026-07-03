import { ChangeDetectorRef, Component, Inject, OnDestroy, OnInit } from '@angular/core';
import { CommonModule, DOCUMENT } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { forkJoin, Subscription } from 'rxjs';

import { TranslatePipe } from '../../core/pipes/translate';
import { AdminService, UserResponse } from '../../core/services/admin';
import { AuthService, RoleEnum } from '../../core/services/auth';
import { DriverResponse, DriverService } from '../../core/services/driver';
import { IncidentService } from '../../core/services/incident';
import { PlanningService } from '../../core/services/planning';
import { TripResponse, TripService, TripStopResponse } from '../../core/services/trip';
import { VehicleResponse, VehicleService } from '../../core/services/vehicle';

@Component({
  selector: 'app-trips',
  imports: [CommonModule, TranslatePipe],
  templateUrl: './trips.html',
  styleUrl: './trips.scss',
})
export class Trips implements OnInit, OnDestroy {
  readonly RoleEnum = RoleEnum;
  trips: TripResponse[] = [];
  selectedTrip: TripResponse | null = null;
  selectedTripStops: TripStopResponse[] = [];
  drivers: DriverResponse[] = [];
  driverUsers: UserResponse[] = [];
  vehicles: VehicleResponse[] = [];
  searchTerm = '';
  statusFilter = '';
  isLoadingTrips = false;
  isLoadingStops = false;
  isLoadingOptions = false;
  isApprovingTrip = false;
  isStartingTrip = false;
  arrivingStopId = '';
  completingStopId = '';
  failingStopId = '';
  selectedFailStop: TripStopResponse | null = null;
  selectedCompletionStop: TripStopResponse | null = null;
  failStopReason = 'ABSENT';
  failStopNotes = '';
  failStopActualKm = '';
  actualKmInput = '';
  actualKmError = '';
  isFailStopOpen = false;
  isActualKmOpen = false;
  isEditTripOpen = false;
  isSavingTrip = false;
  tripsError = '';
  stopsError = '';
  tripActionError = '';
  tripActionSuccess = '';
  editTripError = '';
  editTripSuccess = '';
  editTripDriverId = '';
  editTripVehicleId = '';
  originalEditTripDriverId = '';
  originalEditTripVehicleId = '';
  currentRole: RoleEnum;
  private incidentRefreshSubscription: Subscription;

  readonly tripStatuses = ['PROPOSED', 'APPROVED', 'IN_PROGRESS', 'COMPLETED', 'INTERRUPTED', 'CANCELLED'];
  readonly failureReasons = ['ABSENT', 'REFUSED', 'WRONG_ADDRESS', 'DAMAGED', 'OTHER'];

  constructor(
    private authService: AuthService,
    private adminService: AdminService,
    private tripService: TripService,
    private incidentService: IncidentService,
    private planningService: PlanningService,
    private driverService: DriverService,
    private vehicleService: VehicleService,
    private changeDetectorRef: ChangeDetectorRef,
    @Inject(DOCUMENT) private document: Document,
  ) {
    this.currentRole = this.authService.getCurrentRole();
    this.statusFilter = this.currentRole === RoleEnum.SOFER ? 'APPROVED' : '';
    this.incidentRefreshSubscription = this.incidentService.tripsRefresh$.subscribe(() => {
      this.loadTrips();
    });
  }

  ngOnInit(): void {
    this.loadTrips();
    this.loadOptions();
  }

  ngOnDestroy(): void {
    this.incidentRefreshSubscription.unsubscribe();
    this.unlockBackgroundScroll();
  }

  get canManageTrips(): boolean {
    return [RoleEnum.MANAGER, RoleEnum.DISPECER].includes(this.currentRole);
  }

  get canApproveSelectedTrip(): boolean {
    return Boolean(this.canManageTrips && this.selectedTrip?.status === 'PROPOSED');
  }

  get canEditSelectedTrip(): boolean {
    return Boolean(this.canManageTrips && this.selectedTrip?.status === 'PROPOSED');
  }

  get canStartSelectedTrip(): boolean {
    return Boolean(this.currentRole === RoleEnum.SOFER && this.selectedTrip?.status === 'APPROVED');
  }

  get currentPendingStop(): TripStopResponse | null {
    return this.selectedTripStops.find((stop) => stop.status === 'PENDING') ?? null;
  }

  get visibleStops(): TripStopResponse[] {
    return this.selectedTripStops;
  }

  get hasEditTripChanges(): boolean {
    return (
      this.editTripDriverId !== this.originalEditTripDriverId ||
      this.editTripVehicleId !== this.originalEditTripVehicleId
    );
  }

  get filteredTrips(): TripResponse[] {
    const query = this.searchTerm.trim().toLowerCase();

    if (!query) {
      return this.trips;
    }

    return this.trips.filter((trip) =>
      [
        trip.id,
        trip.status,
        trip.planned_date,
        trip.driver_id ?? '',
        trip.driver_name ?? '',
        this.getDriverLabel(trip.driver_id),
        trip.vehicle_id ?? '',
        trip.vehicle_label ?? '',
        trip.planned_km ?? '',
        trip.actual_km ?? '',
        trip.planned_duration_min ?? '',
        trip.actual_duration_min ?? '',
      ]
        .join(' ')
        .toLowerCase()
        .includes(query),
    );
  }

  loadTrips(): void {
    this.isLoadingTrips = true;
    this.tripsError = '';
    this.tripActionError = '';
    this.changeDetectorRef.detectChanges();

    this.tripService.listTrips(this.statusFilter || undefined).subscribe({
      next: (trips) => {
        const selectedTripId = this.selectedTrip?.id;
        this.trips = trips;
        if (selectedTripId) {
          const refreshedTrip = trips.find((trip) => trip.id === selectedTripId) ?? null;
          this.selectedTrip = refreshedTrip;
          if (refreshedTrip) {
            this.reloadSelectedTripStops(refreshedTrip.id);
          } else {
            this.selectedTripStops = [];
          }
        }
        this.isLoadingTrips = false;
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.tripsError = error.error?.detail ?? 'common.error_generic';
        this.isLoadingTrips = false;
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  loadOptions(): void {
    if (!this.canManageTrips) {
      return;
    }

    this.isLoadingOptions = true;
    this.changeDetectorRef.detectChanges();

    forkJoin({
      drivers: this.driverService.listDrivers(),
      employees: this.adminService.listEmployees(),
      vehicles: this.vehicleService.listVehicles(),
    }).subscribe({
      next: ({ drivers, employees, vehicles }) => {
        this.drivers = drivers;
        this.driverUsers = employees.filter((employee) => employee.role === RoleEnum.SOFER);
        this.vehicles = vehicles;
        this.isLoadingOptions = false;
        this.changeDetectorRef.detectChanges();
      },
      error: () => {
        this.drivers = [];
        this.driverUsers = [];
        this.vehicles = [];
        this.isLoadingOptions = false;
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  updateSearch(value: string): void {
    this.searchTerm = value;
    this.changeDetectorRef.detectChanges();
  }

  updateStatusFilter(value: string): void {
    this.statusFilter = value;
    this.selectedTrip = null;
    this.selectedTripStops = [];
    this.loadTrips();
  }

  selectTrip(trip: TripResponse): void {
    this.selectedTrip = trip;
    this.selectedTripStops = [];
    this.stopsError = '';
    this.tripActionError = '';
    this.tripActionSuccess = '';
    this.reloadSelectedTripStops(trip.id);
  }

  private reloadSelectedTripStops(tripId: string): void {
    this.isLoadingStops = true;
    this.changeDetectorRef.detectChanges();

    this.tripService.listTripStops(tripId).subscribe({
      next: (stops) => {
        this.selectedTripStops = stops;
        this.isLoadingStops = false;
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.stopsError = error.error?.detail ?? 'common.error_generic';
        this.isLoadingStops = false;
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  approveSelectedTrip(): void {
    const trip = this.selectedTrip;

    if (!trip || !this.canApproveSelectedTrip) {
      return;
    }

    this.isApprovingTrip = true;
    this.tripActionError = '';
    this.tripActionSuccess = '';
    this.changeDetectorRef.detectChanges();

    this.tripService.approveTrip(trip.id).subscribe({
      next: (updatedTrip) => {
        this.selectedTrip = updatedTrip;
        this.trips = this.trips
          .map((currentTrip) => (currentTrip.id === updatedTrip.id ? updatedTrip : currentTrip))
          .filter((currentTrip) => !this.statusFilter || currentTrip.status === this.statusFilter);
        this.isApprovingTrip = false;
        this.tripActionSuccess = 'trips.approve_success';
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.tripActionError = error.error?.detail ?? 'common.error_generic';
        this.isApprovingTrip = false;
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  startSelectedTrip(): void {
    const trip = this.selectedTrip;

    if (!trip || !this.canStartSelectedTrip) {
      return;
    }

    this.isStartingTrip = true;
    this.tripActionError = '';
    this.tripActionSuccess = '';
    this.changeDetectorRef.detectChanges();

    this.tripService.startTrip(trip.id).subscribe({
      next: (updatedTrip) => {
        this.selectedTrip = updatedTrip;
        this.trips = this.trips
          .map((currentTrip) => (currentTrip.id === updatedTrip.id ? updatedTrip : currentTrip))
          .filter((currentTrip) => !this.statusFilter || currentTrip.status === this.statusFilter);
        this.isStartingTrip = false;
        this.tripActionSuccess = 'trips.start_success';
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.tripActionError = error.error?.detail ?? 'common.error_generic';
        this.isStartingTrip = false;
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  canArriveAtStop(stop: TripStopResponse): boolean {
    return Boolean(
      this.currentRole === RoleEnum.SOFER &&
        this.selectedTrip?.status === 'IN_PROGRESS' &&
        stop.status === 'PENDING' &&
        !stop.arrival_time &&
        this.currentPendingStop?.id === stop.id,
    );
  }

  isArriveStopDisabled(stop: TripStopResponse): boolean {
    return Boolean(stop.arrival_time || !this.canArriveAtStop(stop) || this.arrivingStopId === stop.id);
  }

  canCompleteStop(stop: TripStopResponse): boolean {
    return Boolean(
      this.currentRole === RoleEnum.SOFER &&
        this.selectedTrip?.status === 'IN_PROGRESS' &&
        stop.status === 'PENDING' &&
        stop.arrival_time &&
        this.currentPendingStop?.id === stop.id,
    );
  }

  isCompleteStopDisabled(stop: TripStopResponse): boolean {
    return !this.canCompleteStop(stop) || this.completingStopId === stop.id;
  }

  canFailStop(stop: TripStopResponse): boolean {
    return Boolean(
      this.currentRole === RoleEnum.SOFER &&
        this.selectedTrip?.status === 'IN_PROGRESS' &&
        stop.status === 'PENDING' &&
        stop.arrival_time &&
        this.currentPendingStop?.id === stop.id,
    );
  }

  isFailStopDisabled(stop: TripStopResponse): boolean {
    return !this.canFailStop(stop) || this.failingStopId === stop.id;
  }

  isStopDisabled(stop: TripStopResponse): boolean {
    return Boolean(
      this.currentRole === RoleEnum.SOFER &&
        this.selectedTrip?.status === 'IN_PROGRESS' &&
        stop.status === 'PENDING' &&
        this.currentPendingStop?.id !== stop.id,
    );
  }

  arriveAtStop(stop: TripStopResponse): void {
    const trip = this.selectedTrip;

    if (!trip || !this.canArriveAtStop(stop)) {
      return;
    }

    this.arrivingStopId = stop.id;
    this.stopsError = '';
    this.tripActionSuccess = '';
    this.changeDetectorRef.detectChanges();

    this.tripService.arriveAtStop(trip.id, stop.id).subscribe({
      next: (updatedStop) => {
        this.selectedTripStops = this.selectedTripStops.map((currentStop) =>
          currentStop.id === updatedStop.id ? updatedStop : currentStop,
        );
        this.arrivingStopId = '';
        this.tripActionSuccess = 'trips.arrive_success';
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.stopsError = error.error?.detail ?? 'common.error_generic';
        this.arrivingStopId = '';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  completeStop(stop: TripStopResponse): void {
    if (!this.selectedTrip || !this.canCompleteStop(stop)) {
      return;
    }

    if (this.willFinishTrip(stop) && this.selectedTrip.actual_km === null) {
      this.selectedCompletionStop = stop;
      this.actualKmInput = '';
      this.actualKmError = '';
      this.isActualKmOpen = true;
      this.lockBackgroundScroll();
      this.changeDetectorRef.detectChanges();
      return;
    }

    this.executeCompleteStop(stop);
  }

  willFinishTrip(stop: TripStopResponse): boolean {
    const remaining = this.selectedTripStops.filter((candidate) => {
      if (candidate.status !== 'PENDING' || candidate.id === stop.id) {
        return false;
      }

      const skippedByFailedPickup =
        stop.stop_type === 'PICKUP' &&
        candidate.order_id === stop.order_id &&
        candidate.stop_type === 'DELIVERY';

      return !skippedByFailedPickup;
    });

    return remaining.length === 0;
  }

  closeActualKmWindow(): void {
    if (this.completingStopId) {
      return;
    }

    this.isActualKmOpen = false;
    this.selectedCompletionStop = null;
    this.actualKmInput = '';
    this.actualKmError = '';
    this.unlockBackgroundScroll();
    this.changeDetectorRef.detectChanges();
  }

  updateActualKm(value: string): void {
    this.actualKmInput = value;
    this.actualKmError = '';
    this.changeDetectorRef.detectChanges();
  }

  submitFinalStop(): void {
    const stop = this.selectedCompletionStop;
    const actualKm = Number(this.actualKmInput);

    if (!stop || !Number.isFinite(actualKm) || actualKm <= 0) {
      this.actualKmError = 'trips.actual_km_invalid';
      this.changeDetectorRef.detectChanges();
      return;
    }

    this.executeCompleteStop(stop, actualKm);
  }

  private executeCompleteStop(stop: TripStopResponse, actualKm?: number): void {
    const trip = this.selectedTrip;
    if (!trip || !this.canCompleteStop(stop)) {
      return;
    }

    this.completingStopId = stop.id;
    this.stopsError = '';
    this.actualKmError = '';
    this.tripActionSuccess = '';
    this.changeDetectorRef.detectChanges();

    this.tripService.completeStop(trip.id, stop.id, { actual_km: actualKm }).subscribe({
      next: (updatedStop) => {
        this.selectedTripStops = this.selectedTripStops.map((currentStop) =>
          currentStop.id === updatedStop.id ? updatedStop : currentStop,
        );
        this.tripActionSuccess = 'trips.complete_success';
        if (this.isActualKmOpen) {
          this.isActualKmOpen = false;
          this.selectedCompletionStop = null;
          this.actualKmInput = '';
          this.unlockBackgroundScroll();
        }
        this.refreshSelectedTripAfterStopAction(trip.id, () => {
          this.completingStopId = '';
        });
      },
      error: (error: HttpErrorResponse) => {
        this.stopsError = error.error?.detail ?? 'common.error_generic';
        this.completingStopId = '';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  openFailStop(stop: TripStopResponse): void {
    if (!this.canFailStop(stop)) {
      return;
    }

    this.selectedFailStop = stop;
    this.failStopReason = 'ABSENT';
    this.failStopNotes = '';
    this.failStopActualKm = '';
    this.stopsError = '';
    this.tripActionSuccess = '';
    this.isFailStopOpen = true;
    this.lockBackgroundScroll();
    this.changeDetectorRef.detectChanges();
  }

  closeFailStop(): void {
    this.isFailStopOpen = false;
    this.selectedFailStop = null;
    this.failStopReason = 'ABSENT';
    this.failStopNotes = '';
    this.failStopActualKm = '';
    this.failingStopId = '';
    this.unlockBackgroundScroll();
    this.changeDetectorRef.detectChanges();
  }

  updateFailStopReason(value: string): void {
    this.failStopReason = value;
    this.changeDetectorRef.detectChanges();
  }

  updateFailStopNotes(value: string): void {
    this.failStopNotes = value;
    this.changeDetectorRef.detectChanges();
  }

  updateFailStopActualKm(value: string): void {
    this.failStopActualKm = value;
    this.stopsError = '';
    this.changeDetectorRef.detectChanges();
  }

  submitFailStop(): void {
    const trip = this.selectedTrip;
    const stop = this.selectedFailStop;

    if (!trip || !stop || !this.canFailStop(stop)) {
      return;
    }

    const finishesTrip = this.willFinishTrip(stop);
    const actualKm = Number(this.failStopActualKm);
    if (finishesTrip && (!Number.isFinite(actualKm) || actualKm <= 0)) {
      this.stopsError = 'trips.actual_km_invalid';
      this.changeDetectorRef.detectChanges();
      return;
    }

    this.failingStopId = stop.id;
    this.stopsError = '';
    this.tripActionSuccess = '';
    this.changeDetectorRef.detectChanges();

    this.tripService
      .failStop(trip.id, stop.id, {
        failure_reason: this.failStopReason,
        notes: this.failStopNotes.trim() || null,
        actual_km: finishesTrip ? actualKm : null,
      })
      .subscribe({
        next: () => {
          this.tripService.listTripStops(trip.id).subscribe({
            next: (stops) => {
              this.selectedTripStops = stops;
              this.isFailStopOpen = false;
              this.selectedFailStop = null;
              this.tripActionSuccess = 'trips.fail_success';
              this.unlockBackgroundScroll();
              this.refreshSelectedTripAfterStopAction(trip.id, () => {
                this.failingStopId = '';
              });
            },
            error: (error: HttpErrorResponse) => {
              this.stopsError = error.error?.detail ?? 'common.error_generic';
              this.failingStopId = '';
              this.unlockBackgroundScroll();
              this.changeDetectorRef.detectChanges();
            },
          });
        },
        error: (error: HttpErrorResponse) => {
          this.stopsError = error.error?.detail ?? 'common.error_generic';
          this.failingStopId = '';
          this.changeDetectorRef.detectChanges();
        },
      });
  }

  private refreshSelectedTripAfterStopAction(tripId: string, finalize: () => void): void {
    this.tripService.getTrip(tripId).subscribe({
      next: (updatedTrip) => {
        this.selectedTrip = updatedTrip;
        this.trips = this.trips.map((currentTrip) =>
          currentTrip.id === updatedTrip.id ? updatedTrip : currentTrip,
        );
        finalize();
        this.changeDetectorRef.detectChanges();
      },
      error: () => {
        finalize();
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  openEditTrip(): void {
    const trip = this.selectedTrip;

    if (!trip || !this.canEditSelectedTrip) {
      return;
    }

    this.editTripDriverId = trip.driver_id ?? '';
    this.editTripVehicleId = trip.vehicle_id ?? '';
    this.originalEditTripDriverId = trip.driver_id ?? '';
    this.originalEditTripVehicleId = trip.vehicle_id ?? '';
    this.editTripError = '';
    this.editTripSuccess = '';
    this.isEditTripOpen = true;
    this.lockBackgroundScroll();
    this.changeDetectorRef.detectChanges();
    this.loadOptions();
  }

  closeEditTrip(): void {
    this.isEditTripOpen = false;
    this.isSavingTrip = false;
    this.editTripError = '';
    this.editTripSuccess = '';
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

  saveTripChanges(): void {
    const trip = this.selectedTrip;

    if (!trip || !this.hasEditTripChanges) {
      return;
    }

    const requests = [];

    if (this.editTripDriverId && this.editTripDriverId !== this.originalEditTripDriverId) {
      requests.push(this.planningService.changeTripDriver(trip.id, this.editTripDriverId));
    }

    if (this.editTripVehicleId && this.editTripVehicleId !== this.originalEditTripVehicleId) {
      requests.push(this.planningService.changeTripVehicle(trip.id, this.editTripVehicleId));
    }

    if (!requests.length) {
      return;
    }

    this.isSavingTrip = true;
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

        this.selectedTrip = updatedTrip;
        this.trips = this.trips.map((currentTrip) =>
          currentTrip.id === updatedTrip.id ? updatedTrip : currentTrip,
        );
        this.originalEditTripDriverId = this.editTripDriverId;
        this.originalEditTripVehicleId = this.editTripVehicleId;
        this.isSavingTrip = false;
        this.editTripSuccess = 'trips.update_success';
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.editTripError = error.error?.detail ?? 'common.error_generic';
        this.isSavingTrip = false;
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  getDriverLabel(driverId: string | null): string {
    const driver = this.drivers.find((currentDriver) => currentDriver.id === driverId);
    const user = this.driverUsers.find((currentUser) => currentUser.id === driver?.user_id);

    return user?.full_name ?? driver?.user_id ?? driverId ?? 'vehicles.not_available';
  }

  getTripDriverLabel(trip: TripResponse): string {
    return trip.driver_name ?? this.getDriverLabel(trip.driver_id);
  }

  getVehicleLabel(vehicleId: string | null): string {
    const vehicle = this.vehicles.find((currentVehicle) => currentVehicle.id === vehicleId);
    return vehicle?.plate ?? vehicleId ?? 'vehicles.not_available';
  }

  getTripVehicleLabel(trip: TripResponse): string {
    return trip.vehicle_label ?? this.getVehicleLabel(trip.vehicle_id);
  }

  getStatusKey(status: string): string {
    return `trips.status.${status.toLowerCase()}`;
  }

  getStatusClass(status: string): string {
    return `trip-status-${status.toLowerCase().replaceAll('_', '-')}`;
  }

  getStopTypeKey(stopType: string): string {
    return `trips.stop_type.${stopType.toLowerCase()}`;
  }

  getStopStatusKey(status: string): string {
    return `trips.stop_status.${status.toLowerCase()}`;
  }

  getFailureReasonKey(reason: string): string {
    return `trips.failure_reason.${reason.toLowerCase()}`;
  }

  getStopAddress(stop: TripStopResponse): string {
    return stop.address ?? stop.order_ref ?? stop.order_id;
  }

  getOrderLabel(stop: TripStopResponse): string {
    return stop.order_ref ?? `Order ${stop.order_id.substring(0, 8)}`;
  }

  getTripLabel(trip: TripResponse): string {
    return `Trip ${trip.planned_date}`;
  }

  private lockBackgroundScroll(): void {
    this.document.body.classList.add('modal-scroll-lock');
  }

  private unlockBackgroundScroll(): void {
    this.document.body.classList.remove('modal-scroll-lock');
  }
}
