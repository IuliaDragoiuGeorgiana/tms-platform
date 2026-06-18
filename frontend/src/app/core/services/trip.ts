import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { AuthService } from './auth';

export interface TripResponse {
  id: string;
  company_id: string;
  driver_id: string | null;
  driver_name?: string | null;
  vehicle_id: string | null;
  vehicle_label?: string | null;
  planned_date: string;
  status: string;
  planned_km: number | null;
  actual_km: number | null;
  planned_duration_min: number | null;
  actual_duration_min: number | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface TripStopResponse {
  id: string;
  trip_id: string;
  order_id: string;
  address?: string | null;
  sequence: number;
  stop_type: string;
  eta_planned: string | null;
  eta_actual: string | null;
  arrival_time: string | null;
  departure_time: string | null;
  status: string;
  failure_reason: string | null;
  notes: string | null;
}

export interface FailStopRequest {
  failure_reason: string;
  notes?: string | null;
}

@Injectable({
  providedIn: 'root',
})
export class TripService {
  private readonly apiUrl = 'http://127.0.0.1:8000/trips';

  constructor(
    private http: HttpClient,
    private authService: AuthService,
  ) {}

  listTrips(statusFilter?: string): Observable<TripResponse[]> {
    const url = statusFilter ? `${this.apiUrl}/?status_filter=${statusFilter}` : `${this.apiUrl}/`;

    return this.http.get<TripResponse[]>(url, {
      headers: this.authService.getAuthHeaders(),
    });
  }

  approveTrip(tripId: string): Observable<TripResponse> {
    return this.http.patch<TripResponse>(
      `${this.apiUrl}/${tripId}/approve`,
      {},
      { headers: this.authService.getAuthHeaders() },
    );
  }

  getTrip(tripId: string): Observable<TripResponse> {
    return this.http.get<TripResponse>(`${this.apiUrl}/${tripId}`, {
      headers: this.authService.getAuthHeaders(),
    });
  }

  startTrip(tripId: string): Observable<TripResponse> {
    return this.http.patch<TripResponse>(
      `${this.apiUrl}/${tripId}/start`,
      {},
      { headers: this.authService.getAuthHeaders() },
    );
  }

  listTripStops(tripId: string): Observable<TripStopResponse[]> {
    return this.http.get<TripStopResponse[]>(`${this.apiUrl}/${tripId}/stops`, {
      headers: this.authService.getAuthHeaders(),
    });
  }

  arriveAtStop(tripId: string, stopId: string): Observable<TripStopResponse> {
    return this.http.patch<TripStopResponse>(
      `${this.apiUrl}/${tripId}/stops/${stopId}/arrive`,
      {},
      { headers: this.authService.getAuthHeaders() },
    );
  }

  completeStop(tripId: string, stopId: string): Observable<TripStopResponse> {
    return this.http.patch<TripStopResponse>(
      `${this.apiUrl}/${tripId}/stops/${stopId}/complete`,
      {},
      { headers: this.authService.getAuthHeaders() },
    );
  }

  failStop(tripId: string, stopId: string, data: FailStopRequest): Observable<TripStopResponse> {
    return this.http.patch<TripStopResponse>(
      `${this.apiUrl}/${tripId}/stops/${stopId}/fail`,
      data,
      { headers: this.authService.getAuthHeaders() },
    );
  }
}
