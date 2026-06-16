import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { AuthService } from './auth';

export interface InviteUserRequest {
  email: string;
  full_name: string;
  role: string;
  company_id?: string | null;
  phone?: string | null;
}

export interface InviteUserResponse {
  message: string;
  user_id: string;
  email: string;
  role: string;
  must_change_password: boolean;
  email_sent: boolean;
}

export interface UserResponse {
  id: string;
  company_id: string | null;
  company_name?: string | null;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  is_approved: boolean;
  must_change_password: boolean;
  phone?: string | null;
}

@Injectable({
  providedIn: 'root',
})
export class AdminService {
  private readonly apiUrl = 'http://127.0.0.1:8000/admin';

  constructor(
    private http: HttpClient,
    private authService: AuthService,
  ) {}

  inviteUser(data: InviteUserRequest): Observable<InviteUserResponse> {
    return this.http.post<InviteUserResponse>(`${this.apiUrl}/users/invite`, data, {
      headers: this.authService.getAuthHeaders(),
    });
  }

  listEmployees(): Observable<UserResponse[]> {
    return this.http.get<UserResponse[]>(`${this.apiUrl}/users/employees`, {
      headers: this.authService.getAuthHeaders(),
    });
  }

  listClients(): Observable<UserResponse[]> {
    return this.http.get<UserResponse[]>(`${this.apiUrl}/clients`, {
      headers: this.authService.getAuthHeaders(),
    });
  }

  activateUser(userId: string): Observable<UserResponse> {
    return this.http.patch<UserResponse>(
      `${this.apiUrl}/users/${userId}/activate`,
      {},
      {
        headers: this.authService.getAuthHeaders(),
      },
    );
  }

  deactivateUser(userId: string): Observable<UserResponse> {
    return this.http.patch<UserResponse>(
      `${this.apiUrl}/users/${userId}/deactivate`,
      {},
      {
        headers: this.authService.getAuthHeaders(),
      },
    );
  }

  approveUser(userId: string): Observable<UserResponse> {
    return this.http.patch<UserResponse>(
      `${this.apiUrl}/users/${userId}/approve`,
      {},
      {
        headers: this.authService.getAuthHeaders(),
      },
    );
  }
}
