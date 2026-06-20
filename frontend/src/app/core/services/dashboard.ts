import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';

import { AuthService } from './auth';

export type ManagerPeriod = 1 | 7 | 30;

export interface ManagerKpi {
  label: string;
  value: string;
  detail: string;
  tone: 'good' | 'warn' | 'danger' | 'neutral';
}

export interface ChartPoint {
  label: string;
  value: number;
}

export interface StatusSlice {
  label: string;
  value: number;
  color: string;
}

export interface DriverWorkload {
  driver: string;
  trips: number;
  stops: number;
}

export interface AttentionItem {
  title: string;
  detail: string;
  severity: 'High' | 'Medium' | 'Low';
}

export interface TripSummary {
  id: string;
  driver: string;
  route: string;
  progress: number;
  status: string;
}

export interface ManagerDashboardData {
  kpis: ManagerKpi[];
  orderTrend: ChartPoint[];
  orderStatus: StatusSlice[];
  tripStatus: ChartPoint[];
  fleetStatus: ChartPoint[];
  driverStatus: ChartPoint[];
  driverWorkload: DriverWorkload[];
  attention: AttentionItem[];
  todayTrips: TripSummary[];
}

export interface SuperAdminKpi {
  label: string;
  value: string;
  detail: string;
  tone: 'good' | 'warn' | 'danger' | 'neutral';
}

export interface SuperAdminKpiSection {
  title: string;
  description: string;
  kpis: SuperAdminKpi[];
}

export interface SuperAdminDashboardData {
  sections: SuperAdminKpiSection[];
}

export interface DispatcherAttentionItem {
  title: string;
  detail: string;
  severity: 'High' | 'Medium' | 'Low';
}

export interface DispatcherDashboardData {
  kpis: ManagerKpi[];
  ongoingTrips: TripSummary[];
  attention: DispatcherAttentionItem[];
}

@Injectable({
  providedIn: 'root',
})
export class DashboardService {
  private readonly apiUrl = 'http://127.0.0.1:8000/dashboard';

  constructor(
    private http: HttpClient,
    private authService: AuthService,
  ) {}

  getManagerDashboard(period: ManagerPeriod): Observable<ManagerDashboardData> {
    const params = new HttpParams().set('period', String(period));

    return this.http.get<ManagerDashboardData>(`${this.apiUrl}/manager`, {
      headers: this.authService.getAuthHeaders(),
      params,
    });
  }

  getSuperAdminDashboard(): Observable<SuperAdminDashboardData> {
    return this.http.get<SuperAdminDashboardData>(`${this.apiUrl}/super-admin`, {
      headers: this.authService.getAuthHeaders(),
    });
  }

  getDispatcherDashboard(): Observable<DispatcherDashboardData> {
    return this.http.get<DispatcherDashboardData>(`${this.apiUrl}/dispatcher`, {
      headers: this.authService.getAuthHeaders(),
    });
  }
}
