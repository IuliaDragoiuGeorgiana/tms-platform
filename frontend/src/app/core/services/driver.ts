import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { AuthService } from './auth';

export interface CreateDriverRequest {
  user_id: string;
  vehicle_id?: string | null;
  shift_start?: string | null;
  shift_end?: string | null;
  max_hours_day: number;
}

export interface UpdateDriverRequest {
  vehicle_id?: string | null;
  shift_start?: string | null;
  shift_end?: string | null;
  max_hours_day?: number | null;
  status?: string | null;
}

export interface DriverResponse {
  id: string;
  company_id: string;
  user_id: string;
  vehicle_id: string | null;
  shift_start: string | null;
  shift_end: string | null;
  max_hours_day: number;
  hours_driven_today: number;
  status: string;
}

@Injectable({
  providedIn: 'root',
})
export class DriverService {
  private readonly apiUrl = 'http://127.0.0.1:8000/drivers';

  constructor(
    private http: HttpClient,
    private authService: AuthService,
  ) {}

  listDrivers(): Observable<DriverResponse[]> {
    return this.http.get<DriverResponse[]>(`${this.apiUrl}/`, {
      headers: this.authService.getAuthHeaders(),
    });
  }

  createDriver(data: CreateDriverRequest): Observable<DriverResponse> {
    return this.http.post<DriverResponse>(`${this.apiUrl}/`, data, {
      headers: this.authService.getAuthHeaders(),
    });
  }

  updateDriver(driverId: string, data: UpdateDriverRequest): Observable<DriverResponse> {
    return this.http.patch<DriverResponse>(`${this.apiUrl}/${driverId}`, data, {
      headers: this.authService.getAuthHeaders(),
    });
  }
}
