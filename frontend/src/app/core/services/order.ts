import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';

import { AuthService } from './auth';

export interface CreateOrderRequest {
  address_pickup: string;
  pickup_time_window_start?: string | null;
  pickup_time_window_end?: string | null;
  address_delivery: string;
  delivery_time_window_start?: string | null;
  delivery_time_window_end?: string | null;
  kg: number;
  m3: number;
  type_marfa: string;
  priority: string;
  delivery_deadline: string;
  earliest_delivery_date?: string | null;
  special_instructions?: string | null;
  client_id?: string | null;
}

export interface MarkOrderProblematicRequest {
  problem_reason: string;
}

export interface UpdateOrderRequest {
  address_pickup?: string;
  pickup_time_window_start?: string | null;
  pickup_time_window_end?: string | null;
  address_delivery?: string;
  delivery_time_window_start?: string | null;
  delivery_time_window_end?: string | null;
  kg?: number;
  m3?: number;
  type_marfa?: string;
  priority?: string;
  delivery_deadline?: string;
  earliest_delivery_date?: string | null;
  special_instructions?: string | null;
}

export interface UpdateOrderServiceTimeRequest {
  pickup_service_minutes: number;
  delivery_service_minutes: number;
}

export interface OrderResponse {
  id: string;
  company_id: string;
  order_ref: string;
  client_id: string;
  address_pickup: string;
  pickup_lat?: number | null;
  pickup_lon?: number | null;
  pickup_time_window_start: string | null;
  pickup_time_window_end: string | null;
  address_delivery: string;
  delivery_lat?: number | null;
  delivery_lon?: number | null;
  delivery_time_window_start: string | null;
  delivery_time_window_end: string | null;
  kg: number;
  m3: number;
  type_marfa: string;
  priority: string;
  pickup_service_minutes?: number | null;
  delivery_service_minutes?: number | null;
  service_time_source?: string;
  delivery_deadline: string;
  earliest_delivery_date: string | null;
  flexibility_days?: number;
  assigned_delivery_date?: string | null;
  status: string;
  tracking_token?: string;
  source?: string;
  attempts_count?: number;
  special_instructions: string | null;
  created_at?: string;
  is_problematic?: boolean;
  problem_reason?: string | null;
}

export interface TrackingResponse {
  order_ref: string;
  status: string;
  delivery_deadline: string;
  address_pickup: string;
  address_delivery: string;
}

export interface OrderFeasibilityResponse {
  is_feasible: boolean;
  warnings: string[];
}

@Injectable({
  providedIn: 'root',
})
export class OrderService {
  private readonly apiUrl = 'http://127.0.0.1:8000/orders';

  constructor(
    private http: HttpClient,
    private authService: AuthService,
  ) {}

  createOrder(data: CreateOrderRequest): Observable<OrderResponse> {
    return this.http.post<OrderResponse>(`${this.apiUrl}/`, data, {
      headers: this.authService.getAuthHeaders(),
    });
  }

  listOrders(): Observable<OrderResponse[]> {
    return this.listOrdersWithFilters();
  }

  listOrdersWithFilters(filters: { status?: string; priority?: string } = {}): Observable<OrderResponse[]> {
    let params = new HttpParams();

    if (filters.status) {
      params = params.set('status', filters.status);
    }

    if (filters.priority) {
      params = params.set('priority', filters.priority);
    }

    return this.http.get<OrderResponse[]>(`${this.apiUrl}/`, {
      headers: this.authService.getAuthHeaders(),
      params,
    });
  }

  trackOrder(trackingToken: string): Observable<TrackingResponse> {
    return this.http.get<TrackingResponse>(
      `${this.apiUrl}/track/${encodeURIComponent(trackingToken)}`,
    );
  }

  markOrderProblematic(orderId: string, data: MarkOrderProblematicRequest): Observable<OrderResponse> {
    return this.http.patch<OrderResponse>(`${this.apiUrl}/${orderId}/mark-problematic`, data, {
      headers: this.authService.getAuthHeaders(),
    });
  }

  updateOrder(orderId: string, data: UpdateOrderRequest): Observable<OrderResponse> {
    return this.http.patch<OrderResponse>(`${this.apiUrl}/${orderId}`, data, {
      headers: this.authService.getAuthHeaders(),
    });
  }

  clearOrderProblematic(orderId: string): Observable<OrderResponse> {
    return this.http.patch<OrderResponse>(
      `${this.apiUrl}/${orderId}/clear-problematic`,
      {},
      {
        headers: this.authService.getAuthHeaders(),
      },
    );
  }

  cancelOrder(orderId: string): Observable<OrderResponse> {
    return this.http.patch<OrderResponse>(
      `${this.apiUrl}/${orderId}/cancel`,
      {},
      {
        headers: this.authService.getAuthHeaders(),
      },
    );
  }

  checkOrderFeasibility(orderId: string): Observable<OrderFeasibilityResponse> {
    return this.http.get<OrderFeasibilityResponse>(`${this.apiUrl}/${orderId}/feasibility`, {
      headers: this.authService.getAuthHeaders(),
    });
  }

  getOrderOperationalWarnings(orderId: string): Observable<OrderFeasibilityResponse> {
    return this.http.get<OrderFeasibilityResponse>(
      `${this.apiUrl}/${orderId}/operational-warnings`,
      {
        headers: this.authService.getAuthHeaders(),
      },
    );
  }

  updateOrderServiceTime(
    orderId: string,
    data: UpdateOrderServiceTimeRequest,
  ): Observable<OrderResponse> {
    return this.http.patch<OrderResponse>(`${this.apiUrl}/${orderId}/service-time`, data, {
      headers: this.authService.getAuthHeaders(),
    });
  }
}
