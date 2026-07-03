import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';

import { AuthService } from './auth';

export interface ZoneDemandItem {
  zone: string;
  orders_count: number;
  pending_orders: number;
  planned_orders: number;
  delivered_orders: number;
  failed_orders: number;
  problematic_orders: number;
  total_kg: number;
  total_m3: number;
  average_kg: number;
  average_m3: number;
  urgent_orders: number;
  critical_orders: number;
  adr_orders: number;
  fragil_orders: number;
  perisabil_orders: number;
  strict_time_window_orders: number;
  unplanned_orders: number;
  zone_demand_score: number;
  demand_level: string;
  recommendation: string;
}

export interface ZoneDemandResponse {
  zones: ZoneDemandItem[];
}

export interface DriverZoneFitItem {
  driver_id: string;
  driver_name: string;
  total_stops_in_zone: number;
  completed_stops_in_zone: number;
  failed_stops_in_zone: number;
  skipped_stops_in_zone: number;
  on_time_rate: number;
  average_delay_minutes: number;
  average_service_minutes: number;
  minor_incidents: number;
  major_incidents: number;
  adr_experience_count: number;
  fragil_experience_count: number;
  perisabil_experience_count: number;
  critical_orders_handled: number;
  driver_zone_fit_score: number;
  recommendation_reason: string[];
}

export interface DriverZoneFitResponse {
  zone: string;
  recommended_drivers: DriverZoneFitItem[];
}

export interface VehicleTripFitItem {
  vehicle_id: string;
  plate: string;
  status: string;
  capacity_kg: number;
  capacity_m3: number;
  required_kg: number;
  required_m3: number;
  load_kg_percent: number;
  load_m3_percent: number;
  capacity_fit: boolean;
  recent_incidents: number;
  major_incidents: number;
  estimated_cost: number | null;
  vehicle_trip_fit_score: number;
  recommendation_reason: string[];
}

export interface VehicleTripFitResponse {
  recommended_vehicles?: VehicleTripFitItem[];
  error?: string;
}

export interface FleetUtilizationTripItem {
  trip_id: string;
  planned_date: string;
  vehicle_id: string;
  vehicle_plate: string;
  orders_count: number;
  stops_count: number;
  total_kg: number;
  total_m3: number;
  vehicle_capacity_kg: number;
  vehicle_capacity_m3: number;
  load_kg_percent: number;
  load_m3_percent: number;
  utilization_level: string;
  recommendation: string;
}

export interface FleetUtilizationSummary {
  used_vehicles: number;
  unused_vehicles: number;
  total_trips: number;
  capacity_compliant_trips: number;
  overloaded_trips: number;
  average_load_kg_percent: number;
  average_load_m3_percent: number;
  underutilized_trips: number;
  normal_trips: number;
  near_capacity_trips: number;
  efficient_trips: number;
}

export interface FleetUtilizationResponse {
  trips: FleetUtilizationTripItem[];
  summary: FleetUtilizationSummary;
}

export interface PlanningQualityResponse {
  planning_session_id: string;
  eligible_orders: number;
  planned_orders: number;
  unplanned_orders: number;
  planned_orders_rate: number;
  total_trips: number;
  total_stops: number;
  average_stops_per_trip: number;
  total_planned_km: number;
  total_planned_duration_min: number;
  warnings_count: number;
  critical_warnings_count: number;
  manual_adjustments_count: number;
  unassigned_trips_count: number;
  planning_quality_score: number;
  quality_level: string;
  recommendation: string;
  error?: string;
}

export interface UnplannedByZoneItem {
  zone: string;
  orders: number;
  kg: number;
  m3: number;
}

export interface UnplannedOrdersResponse {
  total_unplanned_orders: number;
  total_unplanned_kg: number;
  total_unplanned_m3: number;
  critical_unplanned_orders: number;
  urgent_unplanned_orders: number;
  by_reason: Record<string, number>;
  by_zone: UnplannedByZoneItem[];
  recommendations: string[];
}

export interface PlanVsActualGroupItem {
  name: string;
  on_time_rate: number;
  average_delay_minutes: number;
  average_service_minutes: number;
  stops_count: number;
}

export interface PlanVsActualResponse {
  planned_vs_actual_km_difference: number;
  planned_vs_actual_duration_difference: number;
  average_delay_minutes: number;
  max_delay_minutes: number;
  on_time_stops: number;
  late_stops: number;
  on_time_rate: number;
  average_real_service_time: number;
  average_service_time_deviation: number;
  trips_finished_on_time: number;
  trips_delayed: number;
  by_driver: PlanVsActualGroupItem[];
  by_vehicle: PlanVsActualGroupItem[];
  by_zone: PlanVsActualGroupItem[];
}

export interface ServiceTimeAccuracyItem {
  category: string;
  planned_service_minutes_avg: number;
  real_service_minutes_avg: number;
  deviation_minutes: number;
  deviation_percent: number;
  samples_count: number;
  recommendation: string;
}

export interface ServiceTimeAccuracyResponse {
  by_cargo_type: ServiceTimeAccuracyItem[];
  by_zone: ServiceTimeAccuracyItem[];
  by_stop_type: ServiceTimeAccuracyItem[];
}

export interface CostGroupItem {
  name: string;
  orders_count: number;
  trips_count: number;
  total_cost: number;
  cost_per_order: number;
  cost_per_km: number | null;
}

export interface ExpensiveTripItem {
  trip_id: string;
  actual_km: number;
  orders_count: number;
  total_cost: number;
  cost_per_order: number;
  recommendation: string;
}

export interface CostAnalyticsResponse {
  total_planned_cost: number;
  total_actual_cost: number;
  total_extra_cost: number;
  fuel_cost_planned: number;
  fuel_cost_actual: number;
  driver_cost_planned: number;
  driver_cost_actual: number;
  amortization_cost: number;
  cost_per_trip: number;
  cost_per_order: number;
  total_actual_km: number;
  cost_per_km: number | null;
  cost_per_kg: number | null;
  cost_per_m3: number | null;
  planned_vs_actual_variance: number;
  planned_vs_actual_variance_percent: number;
  by_driver: CostGroupItem[];
  by_vehicle: CostGroupItem[];
  by_zone: CostGroupItem[];
  top_expensive_trips: ExpensiveTripItem[];
}

export interface IncidentImpactItem {
  incident_id: string;
  original_trip_id: string;
  type: string;
  created_at: string;
  resolved_at: string | null;
  recovery_trip_id: string | null;
  affected_orders_count: number;
  affected_stops_count: number;
  affected_kg: number;
  affected_m3: number;
  extra_recovery_km: number;
  extra_recovery_duration_min: number;
  extra_recovery_cost: number;
  estimated_delay_minutes: number;
  incident_impact_score: number;
  impact_level: string;
  recommendation: string;
}

export interface IncidentImpactResponse {
  total_incidents: number;
  minor_incidents: number;
  major_incidents: number;
  interrupted_trips: number;
  recovery_trips_created: number;
  incident_rate: number;
  major_incident_rate: number;
  average_recovery_time_minutes: number | null;
  major_incidents_detail: IncidentImpactItem[];
}

@Injectable({
  providedIn: 'root',
})
export class AnalyticsService {
  private readonly apiUrl = 'http://127.0.0.1:8000/analytics';

  constructor(
    private http: HttpClient,
    private authService: AuthService,
  ) {}

  private buildHeaders() {
    return this.authService.getAuthHeaders();
  }

  private buildDateParams(startDate?: string, endDate?: string): HttpParams {
    let params = new HttpParams();
    if (startDate) {
      params = params.set('start_date', startDate);
    }
    if (endDate) {
      params = params.set('end_date', endDate);
    }
    return params;
  }

  getZoneDemand(startDate?: string, endDate?: string): Observable<ZoneDemandResponse> {
    return this.http.get<ZoneDemandResponse>(`${this.apiUrl}/zone-demand`, {
      headers: this.buildHeaders(),
      params: this.buildDateParams(startDate, endDate),
    });
  }

  getDriverZoneFit(zone: string, startDate?: string, endDate?: string): Observable<DriverZoneFitResponse> {
    let params = new HttpParams().set('zone', zone);
    if (startDate) {
      params = params.set('start_date', startDate);
    }
    if (endDate) {
      params = params.set('end_date', endDate);
    }

    return this.http.get<DriverZoneFitResponse>(`${this.apiUrl}/driver-zone-fit`, {
      headers: this.buildHeaders(),
      params,
    });
  }

  getVehicleTripFit(
    tripId?: string,
    orderIds?: string[],
    startDate?: string,
    endDate?: string,
  ): Observable<VehicleTripFitResponse> {
    let params = new HttpParams();
    if (tripId) {
      params = params.set('trip_id', tripId);
    }
    if (orderIds && orderIds.length > 0) {
      params = params.set('order_ids', orderIds.join(','));
    }
    if (startDate) {
      params = params.set('start_date', startDate);
    }
    if (endDate) {
      params = params.set('end_date', endDate);
    }

    return this.http.get<VehicleTripFitResponse>(`${this.apiUrl}/vehicle-trip-fit`, {
      headers: this.buildHeaders(),
      params,
    });
  }

  getFleetUtilization(startDate?: string, endDate?: string): Observable<FleetUtilizationResponse> {
    return this.http.get<FleetUtilizationResponse>(`${this.apiUrl}/fleet-utilization`, {
      headers: this.buildHeaders(),
      params: this.buildDateParams(startDate, endDate),
    });
  }

  getPlanningQuality(planningSessionId: string): Observable<PlanningQualityResponse> {
    return this.http.get<PlanningQualityResponse>(
      `${this.apiUrl}/planning-quality/${encodeURIComponent(planningSessionId)}`,
      {
        headers: this.buildHeaders(),
      },
    );
  }

  getUnplannedOrders(startDate?: string, endDate?: string): Observable<UnplannedOrdersResponse> {
    return this.http.get<UnplannedOrdersResponse>(`${this.apiUrl}/unplanned-orders`, {
      headers: this.buildHeaders(),
      params: this.buildDateParams(startDate, endDate),
    });
  }

  getPlanVsActual(startDate?: string, endDate?: string): Observable<PlanVsActualResponse> {
    return this.http.get<PlanVsActualResponse>(`${this.apiUrl}/plan-vs-actual`, {
      headers: this.buildHeaders(),
      params: this.buildDateParams(startDate, endDate),
    });
  }

  getServiceTimeAccuracy(startDate?: string, endDate?: string): Observable<ServiceTimeAccuracyResponse> {
    return this.http.get<ServiceTimeAccuracyResponse>(`${this.apiUrl}/service-time-accuracy`, {
      headers: this.buildHeaders(),
      params: this.buildDateParams(startDate, endDate),
    });
  }

  getCosts(startDate?: string, endDate?: string): Observable<CostAnalyticsResponse> {
    return this.http.get<CostAnalyticsResponse>(`${this.apiUrl}/costs`, {
      headers: this.buildHeaders(),
      params: this.buildDateParams(startDate, endDate),
    });
  }

  getIncidentImpact(startDate?: string, endDate?: string): Observable<IncidentImpactResponse> {
    return this.http.get<IncidentImpactResponse>(`${this.apiUrl}/incident-impact`, {
      headers: this.buildHeaders(),
      params: this.buildDateParams(startDate, endDate),
    });
  }

  getHealth(): Observable<{ status: string; module: string; endpoints: number }> {
    return this.http.get<{ status: string; module: string; endpoints: number }>(`${this.apiUrl}/health`, {
      headers: this.buildHeaders(),
    });
  }
}
