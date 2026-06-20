import { Injectable } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { BehaviorSubject, Observable } from 'rxjs';

export interface RegisterRequest {
  email: string;
  password: string;
  full_name: string;
  phone?: string | null;
  company_slug: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  must_change_password: boolean;
}

export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
}

export interface ForgotPasswordRequest {
  email: string;
}

export interface ResetPasswordRequest {
  token: string;
  new_password: string;
}

export enum RoleEnum {
  SUPER_ADMIN = 'SUPER_ADMIN',
  MANAGER = 'MANAGER',
  DISPECER = 'DISPECER',
  SOFER = 'SOFER',
  CLIENT = 'CLIENT',
  GUEST = 'GUEST',
}

export interface AuthTokenPayload {
  sub: string;
  role?: RoleEnum;
  company_id?: string | null;
  exp?: number;
}

export interface UserResponse {
  id: string;
  email: string;
  full_name: string;
  role: string;
  company_id?: string | null;
  company_name?: string | null;
  is_active: boolean;
  is_approved: boolean;
  must_change_password: boolean;
  phone?: string | null;
}

@Injectable({
  providedIn: 'root',
})
export class AuthService {
  private readonly apiUrl = 'http://127.0.0.1:8000/auth';
  private readonly loggedInSubject = new BehaviorSubject<boolean>(this.hasStoredToken());
  private readonly roleSubject = new BehaviorSubject<RoleEnum>(this.getCurrentRole());

  readonly isLoggedIn$ = this.loggedInSubject.asObservable();
  readonly role$ = this.roleSubject.asObservable();

  constructor(private http: HttpClient) {}

  register(data: RegisterRequest): Observable<UserResponse> {
    return this.http.post<UserResponse>(`${this.apiUrl}/register`, data);
  }

  login(data: LoginRequest): Observable<TokenResponse> {
    const formData = new FormData();
    formData.append('username', data.email);
    formData.append('password', data.password);

    return this.http.post<TokenResponse>(`${this.apiUrl}/login`, formData);
  }

  changePassword(data: ChangePasswordRequest): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(`${this.apiUrl}/change-password`, data, {
      headers: this.getAuthHeaders(),
    });
  }

  forgotPassword(data: ForgotPasswordRequest): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(`${this.apiUrl}/forgot-password`, data);
  }

  resetPassword(data: ResetPasswordRequest): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(`${this.apiUrl}/reset-password`, data);
  }

  getMe(): Observable<UserResponse> {
    return this.http.get<UserResponse>(`${this.apiUrl}/me`, {
      headers: this.getAuthHeaders(),
    });
  }

  saveSession(token: TokenResponse): void {
    localStorage.setItem('access_token', token.access_token);
    localStorage.setItem('token_type', token.token_type);
    localStorage.setItem('must_change_password', String(token.must_change_password));
    this.loggedInSubject.next(true);
    this.roleSubject.next(this.getCurrentRole());
  }

  markPasswordChanged(): void {
    localStorage.setItem('must_change_password', 'false');
  }

  mustChangePassword(): boolean {
    return localStorage.getItem('must_change_password') === 'true';
  }

  isLoggedIn(): boolean {
    return this.hasStoredToken();
  }

  logout(): void {
    localStorage.removeItem('access_token');
    localStorage.removeItem('token_type');
    localStorage.removeItem('must_change_password');
    this.loggedInSubject.next(false);
    this.roleSubject.next(RoleEnum.GUEST);
  }

  getCurrentRole(): RoleEnum {
    const role = this.decodeStoredToken()?.role;
    return this.isRoleEnum(role) ? role : RoleEnum.GUEST;
  }

  getAuthHeaders(): HttpHeaders {
    const token = localStorage.getItem('access_token');
    return token ? new HttpHeaders({ Authorization: `Bearer ${token}` }) : new HttpHeaders();
  }

  private decodeStoredToken(): AuthTokenPayload | null {
    const token = localStorage.getItem('access_token');

    if (!token) {
      return null;
    }

    try {
      const payload = token.split('.')[1];
      const normalizedPayload = this.normalizeBase64Url(payload);
      return JSON.parse(atob(normalizedPayload)) as AuthTokenPayload;
    } catch {
      return null;
    }
  }

  private normalizeBase64Url(value: string): string {
    const base64 = value.replace(/-/g, '+').replace(/_/g, '/');
    const paddingLength = (4 - (base64.length % 4)) % 4;
    return `${base64}${'='.repeat(paddingLength)}`;
  }

  private hasStoredToken(): boolean {
    return Boolean(localStorage.getItem('access_token'));
  }

  private isRoleEnum(role: unknown): role is RoleEnum {
    return Object.values(RoleEnum).includes(role as RoleEnum);
  }
}
