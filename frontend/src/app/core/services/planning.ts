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

export interface CreateAdHocTripRequest {
  planned_date: string;
  driver_id: string;
  vehicle_id: string;
  order_ids: string[];
}

export interface AdHocTripStopPreview {
  sequence: number;
  order_id: string;
  order_ref: string;
  stop_type: string;
  eta_planned: string | null;
}

export interface AdHocTripWarning {
  type?: string;
  severity?: string;
  order_ref?: string;
  message: string;
}

export interface AdHocTripPreviewResponse {
  planning_session_id: string | null;
  trip_id: string | null;
  planned_date: string;
  status: string;
  driver_id: string;
  driver_name: string | null;
  vehicle_id: string;
  vehicle_plate: string;
  planned_km: number;
  planned_duration_min: number;
  total_orders: number;
  total_stops: number;
  total_kg: number;
  total_m3: number;
  peak_kg: number;
  peak_m3: number;
  driver_available_minutes_before: number;
  driver_remaining_minutes_after: number;
  driver_overtime_minutes: number;
  trip_start_time: string;
  trip_end_time: string;
  orders: Array<{
    order_id: string;
    order_ref: string;
    status: string;
    kg: number;
    m3: number;
  }>;
  stops: AdHocTripStopPreview[];
  warnings: AdHocTripWarning[];
  warnings_count: number;
  message: string;
}

export interface EligibleOrderSummary {
  id: string;
  order_ref: string;
  client_name: string | null;
  status: string;
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
  planned_date?: string | null;
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

  createAdHocTrip(data: CreateAdHocTripRequest): Observable<unknown> {
    return this.http.post(`${this.apiUrl}/ad-hoc`, data, {
      headers: this.authService.getAuthHeaders(),
    });
  }

  previewAdHocTrip(data: CreateAdHocTripRequest): Observable<AdHocTripPreviewResponse> {
    return this.http.post<AdHocTripPreviewResponse>(`${this.apiUrl}/ad-hoc/preview`, data, {
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

  addOrderToTrip(tripId: string, orderId: string): Observable<unknown> {
    return this.http.post(
      `${this.apiUrl}/trips/${tripId}/orders`,
      { order_id: orderId },
      { headers: this.authService.getAuthHeaders() },
    );
  }

  removeOrderFromTrip(tripId: string, orderId: string): Observable<unknown> {
    return this.http.delete(
      `${this.apiUrl}/trips/${tripId}/orders/${orderId}`,
      { headers: this.authService.getAuthHeaders() },
    );
  }
}
