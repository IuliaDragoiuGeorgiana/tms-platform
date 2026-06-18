import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { AuthService } from './auth';

export interface CreateCompanyRequest {
  name: string;
  slug: string;
  plan: string;
  max_vehicles: number;
  max_users: number;
  depot_county?: string | null;
  depot_city?: string | null;
  depot_street?: string | null;
  depot_number?: string | null;
}

export interface UpdateCompanyRequest {
  name?: string;
  is_active?: boolean;
  plan?: string;
  max_vehicles?: number;
  max_users?: number;
  depot_county?: string | null;
  depot_city?: string | null;
  depot_street?: string | null;
  depot_number?: string | null;
}

export interface CompanyResponse {
  id: string;
  name: string;
  slug: string;
  is_active: boolean;
  plan: string;
  max_vehicles: number | null;
  max_users: number | null;
  depot_county: string | null;
  depot_city: string | null;
  depot_street: string | null;
  depot_number: string | null;
  depot_lat: number | null;
  depot_lon: number | null;
  managers_count: number;
  users_count: number;
  dispatchers_count: number;
  drivers_count: number;
  clients_count: number;
  vehicles_count: number;
  created_at: string;
  updated_at: string;
}

export interface CompanyStatsResponse {
  company_id: string;
  company_name: string;
  is_active: boolean;
  total_users: number;
  total_managers: number;
  total_dispatchers: number;
  total_drivers: number;
  total_clients: number;
  total_vehicles: number;
  total_orders: number;
  total_trips: number;
  plan: string;
  max_vehicles: number | null;
  max_users: number | null;
}

export interface PublicCompanyResponse {
  name: string;
  slug: string;
}

@Injectable({
  providedIn: 'root',
})
export class CompanyService {
  private readonly apiUrl = 'http://127.0.0.1:8000/companies';

  constructor(
    private http: HttpClient,
    private authService: AuthService,
  ) {}

  listCompanies(): Observable<CompanyResponse[]> {
    return this.http.get<CompanyResponse[]>(`${this.apiUrl}/`, {
      headers: this.authService.getAuthHeaders(),
    });
  }

  listSignupCompanies(): Observable<PublicCompanyResponse[]> {
    return this.http.get<PublicCompanyResponse[]>(`${this.apiUrl}/public/signup-options`);
  }

  createCompany(data: CreateCompanyRequest): Observable<CompanyResponse> {
    return this.http.post<CompanyResponse>(`${this.apiUrl}/`, data, {
      headers: this.authService.getAuthHeaders(),
    });
  }

  updateCompany(companyId: string, data: UpdateCompanyRequest): Observable<CompanyResponse> {
    return this.http.patch<CompanyResponse>(`${this.apiUrl}/${companyId}`, data, {
      headers: this.authService.getAuthHeaders(),
    });
  }

  getCompanyStats(companyId: string): Observable<CompanyStatsResponse> {
    return this.http.get<CompanyStatsResponse>(`${this.apiUrl}/${companyId}/stats`, {
      headers: this.authService.getAuthHeaders(),
    });
  }

  activateCompany(companyId: string): Observable<CompanyResponse> {
    return this.http.patch<CompanyResponse>(
      `${this.apiUrl}/${companyId}/activate`,
      {},
      {
        headers: this.authService.getAuthHeaders(),
      },
    );
  }

  deactivateCompany(companyId: string): Observable<CompanyResponse> {
    return this.http.patch<CompanyResponse>(
      `${this.apiUrl}/${companyId}/deactivate`,
      {},
      {
        headers: this.authService.getAuthHeaders(),
      },
    );
  }
}
