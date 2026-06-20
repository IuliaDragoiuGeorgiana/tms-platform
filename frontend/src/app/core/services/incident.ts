import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable, Subject } from 'rxjs';

import { AuthService } from './auth';

export interface IncidentReportRequest {
  trip_id: string;
  type: 'MINOR' | 'MAJOR';
  description: string;
  location_city: string;
  location_county: string;
  location_street: string;
  location_number: string;
}

export interface IncidentReportResponse {
  message: string;
  incident_id: string;
  trip_id: string;
  trip_status: string;
  vehicle_id: string | null;
  vehicle_status: string | null;
}

export type IncidentStatusFilter = 'open' | 'resolved' | 'all';
export type IncidentTypeFilter = 'MINOR' | 'MAJOR' | '';

export interface IncidentListResponse {
  id: string;
  trip_id: string;
  trip_status: string | null;
  driver_id: string;
  driver_name: string | null;
  vehicle_id: string;
  vehicle_plate: string | null;
  vehicle_status: string | null;
  type: 'MINOR' | 'MAJOR';
  description: string;
  location_lat: number | null;
  location_lon: number | null;
  created_at: string;
  resolved_at: string | null;
  recovery_trip_id: string | null;
  extra_cost_estimated: number | null;
}

export interface IncidentRouteStopResponse {
  sequence: number;
  node_idx: number;
  order_id: string;
  order_ref: string | null;
  stop_type: string;
  eta_seconds: number;
  is_virtual: boolean;
}

export interface IncidentRecoveryOptionResponse {
  option_id: string;
  type: string;
  feasible: boolean;
  recommended: boolean;
  driver_id: string | null;
  driver_name: string | null;
  vehicle_id: string | null;
  vehicle_plate: string | null;
  planned_km: number;
  planned_duration_min: number;
  estimated_fuel_cost: number;
  estimated_driver_cost: number;
  estimated_total_cost: number;
  late_orders_count: number;
  warnings: string[];
  route: IncidentRouteStopResponse[];
}

export interface ImpactAnalysisResponse {
  incident_id: string;
  original_trip_id: string;
  original_vehicle_id: string | null;
  broken_vehicle_plate: string | null;
  recovery_start_source: string;
  recovery_start_lat: number | null;
  recovery_start_lon: number | null;
  remaining_stops_count: number;
  affected_orders_count: number;
  total_kg: number;
  total_m3: number;
  options: IncidentRecoveryOptionResponse[];
  warnings: string[];
}

export interface RecoverIncidentRequest {
  option_id?: string | null;
  strategy?: string | null;
}

export interface RecoverIncidentResponse {
  message: string;
  incident_id: string;
  original_trip_id: string;
  recovery_trip_id: string | null;
  planned_km: number;
  planned_duration_min: number;
  recovered_stops_count: number;
  recovered_orders_count: number;
  selected_strategy: string;
  postponed_orders_count: number;
  postponed_order_refs: string[];
}

@Injectable({
  providedIn: 'root',
})
export class IncidentService {
  private readonly apiUrl = 'http://127.0.0.1:8000/incidents';
  private readonly tripsRefreshSubject = new Subject<void>();
  readonly tripsRefresh$ = this.tripsRefreshSubject.asObservable();

  constructor(
    private http: HttpClient,
    private authService: AuthService,
  ) {}

  listIncidents(
    statusFilter: IncidentStatusFilter = 'open',
    typeFilter: IncidentTypeFilter = '',
  ): Observable<IncidentListResponse[]> {
    let params = new HttpParams().set('status_filter', statusFilter);

    if (typeFilter) {
      params = params.set('type_filter', typeFilter);
    }

    return this.http.get<IncidentListResponse[]>(`${this.apiUrl}/`, {
      headers: this.authService.getAuthHeaders(),
      params,
    });
  }

  reportIncident(data: IncidentReportRequest): Observable<IncidentReportResponse> {
    return this.http.post<IncidentReportResponse>(`${this.apiUrl}/report`, data, {
      headers: this.authService.getAuthHeaders(),
    });
  }

  notifyTripsRefresh(): void {
    this.tripsRefreshSubject.next();
  }

  getImpactAnalysis(incidentId: string): Observable<ImpactAnalysisResponse> {
    return this.http.get<ImpactAnalysisResponse>(`${this.apiUrl}/${incidentId}/impact-analysis`, {
      headers: this.authService.getAuthHeaders(),
    });
  }

  recoverIncident(
    incidentId: string,
    data: RecoverIncidentRequest,
  ): Observable<RecoverIncidentResponse> {
    return this.http.post<RecoverIncidentResponse>(`${this.apiUrl}/${incidentId}/recover`, data, {
      headers: this.authService.getAuthHeaders(),
    });
  }
}
