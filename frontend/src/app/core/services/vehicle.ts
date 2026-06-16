import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { AuthService } from './auth';

export interface VehicleResponse {
  id: string;
  company_id: string;
  plate: string;
  capacity_kg: number;
  capacity_m3: number;
  type: string;
  status: string;
  fuel_type: string;
  avg_consumption: number | null;
  itp_expiry: string | null;
}

export interface CreateVehicleRequest {
  plate: string;
  capacity_kg: number;
  capacity_m3: number;
  type: string;
  fuel_type: string;
  avg_consumption?: number | null;
  itp_expiry?: string | null;
}

export interface UpdateVehicleRequest {
  plate?: string | null;
  capacity_kg?: number | null;
  capacity_m3?: number | null;
  type?: string | null;
  status?: string | null;
  fuel_type?: string | null;
  avg_consumption?: number | null;
  itp_expiry?: string | null;
}

@Injectable({
  providedIn: 'root',
})
export class VehicleService {
  private readonly apiUrl = 'http://127.0.0.1:8000/vehicles';

  constructor(
    private http: HttpClient,
    private authService: AuthService,
  ) {}

  listVehicles(): Observable<VehicleResponse[]> {
    return this.http.get<VehicleResponse[]>(`${this.apiUrl}/`, {
      headers: this.authService.getAuthHeaders(),
    });
  }

  createVehicle(data: CreateVehicleRequest): Observable<VehicleResponse> {
    return this.http.post<VehicleResponse>(`${this.apiUrl}/`, data, {
      headers: this.authService.getAuthHeaders(),
    });
  }

  updateVehicle(vehicleId: string, data: UpdateVehicleRequest): Observable<VehicleResponse> {
    return this.http.patch<VehicleResponse>(`${this.apiUrl}/${vehicleId}`, data, {
      headers: this.authService.getAuthHeaders(),
    });
  }
}
