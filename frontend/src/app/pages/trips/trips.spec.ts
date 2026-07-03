import { ChangeDetectorRef } from '@angular/core';
import { EMPTY } from 'rxjs';

import { Trips } from './trips';
import { AdminService } from '../../core/services/admin';
import { AuthService, RoleEnum } from '../../core/services/auth';
import { DriverService } from '../../core/services/driver';
import { IncidentService } from '../../core/services/incident';
import { PlanningService } from '../../core/services/planning';
import { TripResponse, TripService, TripStopResponse } from '../../core/services/trip';
import { VehicleService } from '../../core/services/vehicle';

describe('Trips stop workflow', () => {
  it('allows only the driver to process the current stop, after arrival when required', () => {
    const component = new Trips(
      { getCurrentRole: () => RoleEnum.SOFER } as unknown as AuthService,
      {} as AdminService,
      {} as TripService,
      { tripsRefresh$: EMPTY } as unknown as IncidentService,
      {} as PlanningService,
      {} as DriverService,
      {} as VehicleService,
      { detectChanges: vi.fn() } as unknown as ChangeDetectorRef,
      document,
    );

    const firstStop = makeStop('stop-1', 1);
    const secondStop = makeStop('stop-2', 2);
    component.selectedTrip = makeTrip();
    component.selectedTripStops = [firstStop, secondStop];

    expect(component.canArriveAtStop(firstStop)).toBe(true);
    expect(component.canArriveAtStop(secondStop)).toBe(false);
    expect(component.canCompleteStop(firstStop)).toBe(false);
    expect(component.canFailStop(firstStop)).toBe(false);

    firstStop.arrival_time = '2026-07-01T08:00:00Z';
    expect(component.canArriveAtStop(firstStop)).toBe(false);
    expect(component.canCompleteStop(firstStop)).toBe(true);
    expect(component.canFailStop(firstStop)).toBe(true);

    component.currentRole = RoleEnum.MANAGER;
    expect(component.canCompleteStop(firstStop)).toBe(false);

    component.ngOnDestroy();
  });
});

function makeTrip(): TripResponse {
  return {
    id: 'trip-1',
    company_id: 'company-1',
    driver_id: 'driver-1',
    vehicle_id: 'vehicle-1',
    planned_date: '2026-07-01',
    status: 'IN_PROGRESS',
    planned_km: null,
    actual_km: null,
    planned_duration_min: null,
    actual_duration_min: null,
    started_at: '2026-07-01T07:00:00Z',
    completed_at: null,
    created_at: '2026-06-30T12:00:00Z',
  };
}

function makeStop(id: string, sequence: number): TripStopResponse {
  return {
    id,
    trip_id: 'trip-1',
    order_id: `order-${sequence}`,
    sequence,
    stop_type: 'PICKUP',
    eta_planned: null,
    eta_actual: null,
    arrival_time: null,
    departure_time: null,
    status: 'PENDING',
    failure_reason: null,
    notes: null,
  };
}
