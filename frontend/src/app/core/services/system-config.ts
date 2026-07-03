import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { AuthService } from './auth';

export interface ServiceTimeConfigResponse {
  standard_pickup_service_min: number;
  standard_delivery_service_min: number;
  fragil_pickup_service_min: number;
  fragil_delivery_service_min: number;
  perisabil_pickup_service_min: number;
  perisabil_delivery_service_min: number;
  adr_pickup_service_min: number;
  adr_delivery_service_min: number;
  service_extra_minutes_per_500kg: number;
  service_extra_minutes_per_5m3: number;
  service_max_minutes: number;
}

export type UpdateServiceTimeConfigRequest = ServiceTimeConfigResponse;

export interface CostConfigResponse {
  fuel_price_per_liter: number;
  driver_hourly_rate: number;
  vehicle_daily_amortization: number;
  vehicle_consumption_van: number;
  vehicle_consumption_truck: number;
  vehicle_consumption_car: number;
}

export type UpdateCostConfigRequest = CostConfigResponse;

@Injectable({
  providedIn: 'root',
})
export class SystemConfigService {
  private readonly apiUrl = 'http://127.0.0.1:8000/system-config';

  constructor(
    private http: HttpClient,
    private authService: AuthService,
  ) {}

  getServiceTimeConfig(): Observable<ServiceTimeConfigResponse> {
    return this.http.get<ServiceTimeConfigResponse>(`${this.apiUrl}/service-time`, {
      headers: this.authService.getAuthHeaders(),
    });
  }

  updateServiceTimeConfig(data: UpdateServiceTimeConfigRequest): Observable<ServiceTimeConfigResponse> {
    return this.http.put<ServiceTimeConfigResponse>(`${this.apiUrl}/service-time`, data, {
      headers: this.authService.getAuthHeaders(),
    });
  }

  getCostConfig(): Observable<CostConfigResponse> {
    return this.http.get<CostConfigResponse>(this.apiUrl + '/costs', {
      headers: this.authService.getAuthHeaders(),
    });
  }

  updateCostConfig(data: UpdateCostConfigRequest): Observable<CostConfigResponse> {
    return this.http.put<CostConfigResponse>(this.apiUrl + '/costs', data, {
      headers: this.authService.getAuthHeaders(),
    });
  }

}
