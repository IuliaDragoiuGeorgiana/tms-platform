import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { AuthService } from './auth';

export interface EligibleOrdersRequest {
  date_start: string;
  date_end: string;
}

export interface GeneratePlanRequest extends EligibleOrdersRequest {
  strategy: string;
}

export interface EligibleOrderSummary {
  id: string;
  order_ref: string;
  client_name: string | null;
  address_pickup: string;
  address_delivery: string;
  kg: number;
  m3: number;
  type_marfa: string;
  priority: string;
  delivery_deadline: string;
  earliest_delivery_date: string | null;
  flexibility_days: number;
  pickup_time_window_start: string | null;
  pickup_time_window_end: string | null;
  delivery_time_window_start: string | null;
  delivery_time_window_end: string | null;
}

export interface EligibleOrdersResponse {
  date_start: string;
  date_end: string;
  total_eligible: number;
  total_kg: number;
  total_m3: number;
  by_priority: Record<string, number>;
  orders: EligibleOrderSummary[];
}

export interface StrategyComparisonVariant {
  strategy: string;
  error?: string;
  total_orders?: number;
  total_planned?: number;
  total_dropped?: number;
  total_trips?: number;
  total_km?: number;
  total_minutes?: number;
  feasibility?: string;
  orders_on_time?: number;
  delayed_orders_count?: number;
  warnings_count?: number;
  warnings?: StrategyWarningPreview[];
  trips?: StrategyTripPreview[];
}

export interface StrategyWarningPreview {
  order_ref?: string;
  message?: string;
  reason?: string;
  severity?: string;
}

export interface StrategyTripStopPreview {
  order_ref: string;
  order_id: string;
  stop_type: string;
}

export interface StrategyTripPreview {
  trip_id?: string | null;
  driver_id?: string | null;
  driver?: string | null;
  driver_name?: string | null;
  vehicle_id?: string | null;
  vehicle_plate?: string | null;
  saved_driver_id?: string | null;
  saved_driver_name?: string | null;
  saved_vehicle_id?: string | null;
  saved_vehicle_plate?: string | null;
  total_km?: number;
  total_minutes?: number;
  stops?: StrategyTripStopPreview[];
}

export interface StrategyComparisonResponse {
  date_start: string;
  date_end: string;
  variants: StrategyComparisonVariant[];
}

@Injectable({
  providedIn: 'root',
})
export class PlanningService {
  private readonly apiUrl = 'http://127.0.0.1:8000/planning';

  constructor(
    private http: HttpClient,
    private authService: AuthService,
  ) {}

  getEligibleOrders(data: EligibleOrdersRequest): Observable<EligibleOrdersResponse> {
    return this.http.post<EligibleOrdersResponse>(`${this.apiUrl}/eligible-orders`, data, {
      headers: this.authService.getAuthHeaders(),
    });
  }

  compareStrategies(data: EligibleOrdersRequest): Observable<StrategyComparisonResponse> {
    return this.http.post<StrategyComparisonResponse>(`${this.apiUrl}/compare-strategies`, data, {
      headers: this.authService.getAuthHeaders(),
    });
  }

  generatePlanWithStrategy(data: GeneratePlanRequest): Observable<StrategyComparisonVariant> {
    return this.http.post<StrategyComparisonVariant>(`${this.apiUrl}/generate-with-strategy`, data, {
      headers: this.authService.getAuthHeaders(),
    });
  }

  changeTripDriver(tripId: string, driverId: string): Observable<unknown> {
    return this.http.patch(
      `${this.apiUrl}/trips/${tripId}/driver`,
      { driver_id: driverId },
      { headers: this.authService.getAuthHeaders() },
    );
  }

  changeTripVehicle(tripId: string, vehicleId: string): Observable<unknown> {
    return this.http.patch(
      `${this.apiUrl}/trips/${tripId}/vehicle`,
      { vehicle_id: vehicleId },
      { headers: this.authService.getAuthHeaders() },
    );
  }
}
