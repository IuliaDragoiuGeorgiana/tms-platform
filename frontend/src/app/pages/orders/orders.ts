import { ChangeDetectorRef, Component, Inject, OnDestroy, OnInit } from '@angular/core';
import { CommonModule, DOCUMENT } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { catchError, forkJoin, of } from 'rxjs';

import { TranslatePipe } from '../../core/pipes/translate';
import { AuthService, RoleEnum } from '../../core/services/auth';
import { AdminService, UserResponse } from '../../core/services/admin';
import {
  CreateOrderRequest,
  MarkOrderProblematicRequest,
  OrderFeasibilityResponse,
  OrderResponse,
  OrderService,
  UpdateOrderRequest,
  UpdateOrderServiceTimeRequest,
} from '../../core/services/order';

@Component({
  selector: 'app-orders',
  imports: [CommonModule, ReactiveFormsModule, RouterLink, TranslatePipe],
  templateUrl: './orders.html',
  styleUrl: './orders.scss',
})
export class Orders implements OnInit, OnDestroy {
  readonly RoleEnum = RoleEnum;
  readonly currentRole: RoleEnum;
  isCreateOrderOpen = false;
  isCreatingOrder = false;
  isLoadingOrders = false;
  isLoadingClients = false;
  selectedViewOrder: OrderResponse | null = null;
  selectedProblemOrder: OrderResponse | null = null;
  selectedEditOrder: OrderResponse | null = null;
  selectedServiceTimeOrder: OrderResponse | null = null;
  selectedFeasibilityOrder: OrderResponse | null = null;
  selectedCancelOrder: OrderResponse | null = null;
  feasibilityResult: OrderFeasibilityResponse | null = null;
  isCheckingFeasibility = false;
  feasibilityError = '';
  isMarkingProblematic = false;
  isUpdatingOrder = false;
  isUpdatingServiceTime = false;
  isCancellingOrder = false;
  createOrderSuccess = '';
  createOrderError = '';
  markProblematicSuccess = '';
  markProblematicError = '';
  updateOrderSuccess = '';
  updateOrderError = '';
  cancelOrderSuccess = '';
  cancelOrderError = '';
  serviceTimeError = '';
  loadOrdersError = '';
  clientOptionsError = '';
  clientSearchTerm = '';
  orderSearchTerm = '';
  selectedStatus = 'all';
  selectedPriority = 'all';
  selectedCargoType = 'all';
  selectedDeliveryDeadline = '';
  clients: UserResponse[] = [];
  orders: OrderResponse[] = [];
  orderOperationalWarnings = new Map<string, string[]>();

  orderForm;
  problemForm;
  editOrderForm;
  serviceTimeForm;

  constructor(
    private fb: FormBuilder,
    private authService: AuthService,
    private adminService: AdminService,
    private orderService: OrderService,
    private changeDetectorRef: ChangeDetectorRef,
    @Inject(DOCUMENT) private document: Document,
  ) {
    this.currentRole = this.authService.getCurrentRole();
    this.orderForm = this.fb.group({
      client_id: ['', this.currentRole === RoleEnum.CLIENT ? [] : [Validators.required]],
      address_pickup: ['', [Validators.required]],
      pickup_time_window_start: [''],
      pickup_time_window_end: [''],
      address_delivery: ['', [Validators.required]],
      delivery_time_window_start: [''],
      delivery_time_window_end: [''],
      kg: [null as number | null, [Validators.required, Validators.min(0.1)]],
      m3: [null as number | null, [Validators.required, Validators.min(0.1)]],
      type_marfa: ['STANDARD', [Validators.required]],
      priority: ['NORMAL', [Validators.required]],
      earliest_delivery_date: [''],
      delivery_deadline: ['', [Validators.required]],
      special_instructions: [''],
    });
    this.problemForm = this.fb.group({
      problem_reason: ['', [Validators.required]],
    });
    this.editOrderForm = this.fb.group({
      address_pickup: ['', [Validators.required]],
      pickup_time_window_start: [''],
      pickup_time_window_end: [''],
      address_delivery: ['', [Validators.required]],
      delivery_time_window_start: [''],
      delivery_time_window_end: [''],
      kg: [null as number | null, [Validators.required, Validators.min(0.1)]],
      m3: [null as number | null, [Validators.required, Validators.min(0.1)]],
      type_marfa: ['STANDARD', [Validators.required]],
      priority: ['NORMAL', [Validators.required]],
      earliest_delivery_date: [''],
      delivery_deadline: ['', [Validators.required]],
      special_instructions: [''],
    });
    this.serviceTimeForm = this.fb.group({
      pickup_service_minutes: [null as number | null, [Validators.required, Validators.min(1), Validators.max(240)]],
      delivery_service_minutes: [null as number | null, [Validators.required, Validators.min(1), Validators.max(240)]],
    });
  }

  ngOnInit(): void {
    this.loadOrders();
  }

  ngOnDestroy(): void {
    this.unlockBackgroundScroll();
  }

  get filteredClients(): UserResponse[] {
    const query = this.clientSearchTerm.trim().toLowerCase();

    if (!query) {
      return this.clients;
    }

    return this.clients.filter((client) =>
      [client.id, client.full_name, client.email, client.phone ?? '']
        .join(' ')
        .toLowerCase()
        .includes(query),
    );
  }

  get selectedClient(): UserResponse | undefined {
    const selectedClientId = this.orderForm.get('client_id')?.value;
    return this.clients.find((client) => client.id === selectedClientId);
  }

  get filteredOrders(): OrderResponse[] {
    const query = this.orderSearchTerm.trim().toLowerCase();

    return this.orders.filter((order) => {
      const matchesSearch =
        !query ||
        [
          order.id,
          order.order_ref,
          order.client_id,
          order.company_id,
          order.address_pickup,
          order.address_delivery,
          this.getOrderClientLabel(order),
          order.tracking_token ?? '',
          order.special_instructions ?? '',
        ]
          .join(' ')
          .toLowerCase()
          .includes(query);
      const matchesStatus = this.selectedStatus === 'all' || order.status === this.selectedStatus;
      const matchesPriority =
        this.selectedPriority === 'all' || order.priority === this.selectedPriority;
      const matchesCargoType =
        this.selectedCargoType === 'all' || order.type_marfa === this.selectedCargoType;
      const matchesDeliveryDeadline =
        !this.selectedDeliveryDeadline || order.delivery_deadline === this.selectedDeliveryDeadline;

      return (
        matchesSearch &&
        matchesStatus &&
        matchesPriority &&
        matchesCargoType &&
        matchesDeliveryDeadline
      );
    });
  }

  loadOrders(): void {
    this.isLoadingOrders = true;
    this.loadOrdersError = '';
    this.changeDetectorRef.detectChanges();

    this.orderService
      .listOrdersWithFilters({
        status: this.selectedStatus === 'all' ? undefined : this.selectedStatus,
        priority: this.selectedPriority === 'all' ? undefined : this.selectedPriority,
      })
      .subscribe({
      next: (orders) => {
        this.orders = orders;
        this.isLoadingOrders = false;
        this.loadOperationalWarnings(orders);
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isLoadingOrders = false;
        this.loadOrdersError = error.error?.detail ?? 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  updateOrderSearch(value: string): void {
    this.orderSearchTerm = value;
  }

  updateStatusFilter(value: string): void {
    this.selectedStatus = value;
    this.loadOrders();
  }

  updatePriorityFilter(value: string): void {
    this.selectedPriority = value;
    this.loadOrders();
  }

  updateCargoTypeFilter(value: string): void {
    this.selectedCargoType = value;
    this.changeDetectorRef.detectChanges();
  }

  updateDeliveryDeadlineFilter(value: string): void {
    this.selectedDeliveryDeadline = value;
    this.changeDetectorRef.detectChanges();
  }

  clearOrderFilters(): void {
    this.orderSearchTerm = '';
    this.selectedStatus = 'all';
    this.selectedPriority = 'all';
    this.selectedCargoType = 'all';
    this.selectedDeliveryDeadline = '';
    this.loadOrders();
  }

  openCreateOrder(): void {
    this.isCreateOrderOpen = true;
    this.createOrderSuccess = '';
    this.createOrderError = '';
    this.lockBackgroundScroll();
    if (this.currentRole !== RoleEnum.CLIENT) {
      this.loadClients();
    }
    this.changeDetectorRef.detectChanges();
  }

  closeCreateOrder(): void {
    this.isCreateOrderOpen = false;
    this.createOrderError = '';
    this.clientOptionsError = '';
    this.clientSearchTerm = '';
    this.orderForm.reset({
      client_id: '',
      address_pickup: '',
      pickup_time_window_start: '',
      pickup_time_window_end: '',
      address_delivery: '',
      delivery_time_window_start: '',
      delivery_time_window_end: '',
      kg: null,
      m3: null,
      type_marfa: 'STANDARD',
      priority: 'NORMAL',
      earliest_delivery_date: '',
      delivery_deadline: '',
      special_instructions: '',
    });
    this.unlockBackgroundScroll();
    this.changeDetectorRef.detectChanges();
  }

  openViewOrder(order: OrderResponse): void {
    this.selectedViewOrder = order;
    this.lockBackgroundScroll();
    this.changeDetectorRef.detectChanges();
  }

  closeViewOrder(): void {
    this.selectedViewOrder = null;
    this.unlockBackgroundScroll();
    this.changeDetectorRef.detectChanges();
  }

  openMarkProblematic(order: OrderResponse): void {
    this.selectedProblemOrder = order;
    this.markProblematicError = '';
    this.problemForm.reset({ problem_reason: '' });
    this.lockBackgroundScroll();
    this.changeDetectorRef.detectChanges();
  }

  openEditOrder(order: OrderResponse): void {
    this.selectedEditOrder = order;
    this.updateOrderError = '';
    this.updateOrderSuccess = '';
    this.editOrderForm.reset({
      address_pickup: order.address_pickup,
      pickup_time_window_start: order.pickup_time_window_start ?? '',
      pickup_time_window_end: order.pickup_time_window_end ?? '',
      address_delivery: order.address_delivery,
      delivery_time_window_start: order.delivery_time_window_start ?? '',
      delivery_time_window_end: order.delivery_time_window_end ?? '',
      kg: order.kg,
      m3: order.m3,
      type_marfa: order.type_marfa,
      priority: order.priority,
      earliest_delivery_date: order.earliest_delivery_date ?? '',
      delivery_deadline: order.delivery_deadline,
      special_instructions: order.special_instructions ?? '',
    });
    this.lockBackgroundScroll();
    this.changeDetectorRef.detectChanges();
  }

  closeEditOrder(): void {
    this.selectedEditOrder = null;
    this.updateOrderError = '';
    this.editOrderForm.reset({
      address_pickup: '',
      pickup_time_window_start: '',
      pickup_time_window_end: '',
      address_delivery: '',
      delivery_time_window_start: '',
      delivery_time_window_end: '',
      kg: null,
      m3: null,
      type_marfa: 'STANDARD',
      priority: 'NORMAL',
      earliest_delivery_date: '',
      delivery_deadline: '',
      special_instructions: '',
    });
    this.unlockBackgroundScroll();
    this.changeDetectorRef.detectChanges();
  }

  closeMarkProblematic(): void {
    this.selectedProblemOrder = null;
    this.markProblematicError = '';
    this.problemForm.reset({ problem_reason: '' });
    this.unlockBackgroundScroll();
    this.changeDetectorRef.detectChanges();
  }

  openServiceTime(order: OrderResponse): void {
    this.selectedServiceTimeOrder = order;
    this.serviceTimeError = '';
    this.serviceTimeForm.reset({
      pickup_service_minutes: order.pickup_service_minutes ?? 30,
      delivery_service_minutes: order.delivery_service_minutes ?? 30,
    });
    this.lockBackgroundScroll();
    this.changeDetectorRef.detectChanges();
  }

  closeServiceTime(): void {
    this.selectedServiceTimeOrder = null;
    this.serviceTimeError = '';
    this.serviceTimeForm.reset({
      pickup_service_minutes: null,
      delivery_service_minutes: null,
    });
    this.unlockBackgroundScroll();
    this.changeDetectorRef.detectChanges();
  }

  openFeasibilityCheck(order: OrderResponse): void {
    this.selectedFeasibilityOrder = order;
    this.feasibilityResult = null;
    this.feasibilityError = '';
    this.lockBackgroundScroll();
    this.changeDetectorRef.detectChanges();
    this.checkSelectedOrderFeasibility();
  }

  closeFeasibilityCheck(): void {
    this.selectedFeasibilityOrder = null;
    this.feasibilityResult = null;
    this.feasibilityError = '';
    this.unlockBackgroundScroll();
    this.changeDetectorRef.detectChanges();
  }

  openCancelOrder(order: OrderResponse): void {
    this.selectedCancelOrder = order;
    this.cancelOrderError = '';
    this.lockBackgroundScroll();
    this.changeDetectorRef.detectChanges();
  }

  closeCancelOrder(): void {
    this.selectedCancelOrder = null;
    this.cancelOrderError = '';
    this.unlockBackgroundScroll();
    this.changeDetectorRef.detectChanges();
  }

  loadClients(): void {
    this.isLoadingClients = true;
    this.clientOptionsError = '';
    this.changeDetectorRef.detectChanges();

    this.adminService.listClients().subscribe({
      next: (clients) => {
        this.clients = clients;
        this.isLoadingClients = false;
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isLoadingClients = false;

        if (error.error?.detail) {
          this.clientOptionsError = error.error.detail;
          this.changeDetectorRef.detectChanges();
          return;
        }

        this.clientOptionsError = 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  updateClientSearch(value: string): void {
    this.clientSearchTerm = value;
  }

  selectClient(client: UserResponse): void {
    this.orderForm.patchValue({ client_id: client.id });
    this.orderForm.get('client_id')?.markAsTouched();
  }

  createOrder(): void {
    this.createOrderSuccess = '';
    this.createOrderError = '';

    if (this.orderForm.invalid) {
      this.orderForm.markAllAsTouched();
      return;
    }

    const formValue = this.orderForm.value;
    const payload: CreateOrderRequest = {
      address_pickup: formValue.address_pickup ?? '',
      pickup_time_window_start: formValue.pickup_time_window_start || null,
      pickup_time_window_end: formValue.pickup_time_window_end || null,
      address_delivery: formValue.address_delivery ?? '',
      delivery_time_window_start: formValue.delivery_time_window_start || null,
      delivery_time_window_end: formValue.delivery_time_window_end || null,
      kg: Number(formValue.kg),
      m3: Number(formValue.m3),
      type_marfa: formValue.type_marfa ?? 'STANDARD',
      priority: formValue.priority ?? 'NORMAL',
      earliest_delivery_date: formValue.earliest_delivery_date || null,
      delivery_deadline: formValue.delivery_deadline ?? '',
      special_instructions: formValue.special_instructions || null,
    };

    if (this.currentRole !== RoleEnum.CLIENT) {
      payload.client_id = formValue.client_id ?? '';
    }

    this.isCreatingOrder = true;
    this.changeDetectorRef.detectChanges();

    this.orderService.createOrder(payload).subscribe({
      next: (order) => {
        this.isCreatingOrder = false;
        this.orders = [order, ...this.orders];
        this.loadOperationalWarnings(this.orders);
        this.closeCreateOrder();
        this.createOrderSuccess = 'orders.create_success';
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isCreatingOrder = false;

        if (error.error?.detail) {
          this.createOrderError = error.error.detail;
          this.changeDetectorRef.detectChanges();
          return;
        }

        this.createOrderError = 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  markSelectedOrderProblematic(): void {
    this.markProblematicSuccess = '';
    this.markProblematicError = '';

    if (!this.selectedProblemOrder) {
      return;
    }

    if (this.problemForm.invalid) {
      this.problemForm.markAllAsTouched();
      return;
    }

    const payload: MarkOrderProblematicRequest = {
      problem_reason: this.problemForm.value.problem_reason?.trim() ?? '',
    };
    const orderId = this.selectedProblemOrder.id;

    this.isMarkingProblematic = true;
    this.changeDetectorRef.detectChanges();

    this.orderService.markOrderProblematic(orderId, payload).subscribe({
      next: (updatedOrder) => {
        this.isMarkingProblematic = false;
        this.orders = this.orders.map((order) => (order.id === updatedOrder.id ? updatedOrder : order));
        if (this.selectedViewOrder?.id === updatedOrder.id) {
          this.selectedViewOrder = updatedOrder;
        }
        this.closeMarkProblematic();
        this.markProblematicSuccess = 'orders.mark_problematic_success';
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isMarkingProblematic = false;
        this.markProblematicError = error.error?.detail ?? 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  updateSelectedOrder(): void {
    this.updateOrderSuccess = '';
    this.updateOrderError = '';

    if (!this.selectedEditOrder) {
      return;
    }

    if (this.editOrderForm.invalid) {
      this.editOrderForm.markAllAsTouched();
      return;
    }

    const formValue = this.editOrderForm.value;
    const payload: UpdateOrderRequest = {
      address_pickup: formValue.address_pickup ?? '',
      pickup_time_window_start: formValue.pickup_time_window_start || null,
      pickup_time_window_end: formValue.pickup_time_window_end || null,
      address_delivery: formValue.address_delivery ?? '',
      delivery_time_window_start: formValue.delivery_time_window_start || null,
      delivery_time_window_end: formValue.delivery_time_window_end || null,
      kg: Number(formValue.kg),
      m3: Number(formValue.m3),
      type_marfa: formValue.type_marfa ?? 'STANDARD',
      priority: formValue.priority ?? 'NORMAL',
      earliest_delivery_date: formValue.earliest_delivery_date || null,
      delivery_deadline: formValue.delivery_deadline ?? '',
      special_instructions: formValue.special_instructions || null,
    };
    const orderId = this.selectedEditOrder.id;

    this.isUpdatingOrder = true;
    this.changeDetectorRef.detectChanges();

    this.orderService.updateOrder(orderId, payload).subscribe({
      next: (updatedOrder) => {
        this.isUpdatingOrder = false;
        this.orders = this.orders.map((order) => (order.id === updatedOrder.id ? updatedOrder : order));
        if (this.selectedViewOrder?.id === updatedOrder.id) {
          this.selectedViewOrder = updatedOrder;
        }
        this.loadOperationalWarnings(this.orders);
        this.closeEditOrder();
        this.updateOrderSuccess = 'orders.update_success';
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isUpdatingOrder = false;
        this.updateOrderError = error.error?.detail ?? 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  clearSelectedOrderProblematic(): void {
    this.updateOrderSuccess = '';
    this.updateOrderError = '';

    if (!this.selectedEditOrder) {
      return;
    }

    const orderId = this.selectedEditOrder.id;
    this.isUpdatingOrder = true;
    this.changeDetectorRef.detectChanges();

    this.orderService.clearOrderProblematic(orderId).subscribe({
      next: (updatedOrder) => {
        this.isUpdatingOrder = false;
        this.orders = this.orders.map((order) => (order.id === updatedOrder.id ? updatedOrder : order));
        this.selectedEditOrder = updatedOrder;
        if (this.selectedViewOrder?.id === updatedOrder.id) {
          this.selectedViewOrder = updatedOrder;
        }
        this.loadOperationalWarnings(this.orders);
        this.updateOrderSuccess = 'orders.clear_problematic_success';
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isUpdatingOrder = false;
        this.updateOrderError = error.error?.detail ?? 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  checkSelectedOrderFeasibility(): void {
    this.feasibilityResult = null;
    this.feasibilityError = '';

    if (!this.selectedFeasibilityOrder) {
      return;
    }

    this.isCheckingFeasibility = true;
    this.changeDetectorRef.detectChanges();

    this.orderService.checkOrderFeasibility(this.selectedFeasibilityOrder.id).subscribe({
      next: (result) => {
        this.isCheckingFeasibility = false;
        this.feasibilityResult = {
          is_feasible: result.is_feasible,
          warnings: [...result.warnings],
        };
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isCheckingFeasibility = false;
        this.feasibilityError = error.error?.detail ?? 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  updateSelectedOrderServiceTime(): void {
    this.serviceTimeError = '';

    if (!this.selectedServiceTimeOrder) {
      return;
    }

    if (this.serviceTimeForm.invalid) {
      this.serviceTimeForm.markAllAsTouched();
      return;
    }

    const formValue = this.serviceTimeForm.value;
    const payload: UpdateOrderServiceTimeRequest = {
      pickup_service_minutes: Number(formValue.pickup_service_minutes),
      delivery_service_minutes: Number(formValue.delivery_service_minutes),
    };
    const orderId = this.selectedServiceTimeOrder.id;

    this.isUpdatingServiceTime = true;
    this.changeDetectorRef.detectChanges();

    this.orderService.updateOrderServiceTime(orderId, payload).subscribe({
      next: (updatedOrder) => {
        this.isUpdatingServiceTime = false;
        this.orders = this.orders.map((order) => (order.id === updatedOrder.id ? updatedOrder : order));
        if (this.selectedViewOrder?.id === updatedOrder.id) {
          this.selectedViewOrder = updatedOrder;
        }
        this.loadOperationalWarnings(this.orders);
        this.closeServiceTime();
        this.updateOrderSuccess = 'orders.service_time_success';
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isUpdatingServiceTime = false;
        this.serviceTimeError = error.error?.detail ?? 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  cancelSelectedOrder(): void {
    this.cancelOrderSuccess = '';
    this.cancelOrderError = '';

    if (!this.selectedCancelOrder) {
      return;
    }

    const orderId = this.selectedCancelOrder.id;

    this.isCancellingOrder = true;
    this.changeDetectorRef.detectChanges();

    this.orderService.cancelOrder(orderId).subscribe({
      next: (updatedOrder) => {
        this.isCancellingOrder = false;
        this.orders = this.orders.map((order) => (order.id === updatedOrder.id ? updatedOrder : order));
        if (this.selectedViewOrder?.id === updatedOrder.id) {
          this.selectedViewOrder = updatedOrder;
        }
        this.loadOperationalWarnings(this.orders);
        this.closeCancelOrder();
        this.cancelOrderSuccess = 'orders.cancel_order_success';
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isCancellingOrder = false;
        this.cancelOrderError = error.error?.detail ?? 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  getOrderStatusKey(order: OrderResponse): string {
    return `orders.status.${order.status.toLowerCase()}`;
  }

  getOrderPriorityKey(order: OrderResponse): string {
    return `orders.priority.${order.priority.toLowerCase()}`;
  }

  getOrderCargoTypeKey(order: OrderResponse): string {
    const cargoTypeMap: Record<string, string> = {
      STANDARD: 'orders.cargo.standard',
      FRAGIL: 'orders.cargo.fragile',
      PERISABIL: 'orders.cargo.perishable',
      ADR: 'orders.cargo.adr',
    };

    return cargoTypeMap[order.type_marfa] ?? order.type_marfa;
  }

  getOrderClientLabel(order: OrderResponse): string {
    const client = this.clients.find((existingClient) => existingClient.id === order.client_id);
    return client?.full_name ?? order.client_id;
  }

  canMarkProblematic(order: OrderResponse): boolean {
    return (
      (this.currentRole === RoleEnum.MANAGER || this.currentRole === RoleEnum.DISPECER) &&
      order.status === 'PENDING' &&
      !order.is_problematic
    );
  }

  canEditOrder(order: OrderResponse): boolean {
    return (
      (this.currentRole === RoleEnum.MANAGER || this.currentRole === RoleEnum.DISPECER) &&
      order.status === 'PENDING'
    );
  }

  canCancelOrder(order: OrderResponse): boolean {
    return this.currentRole === RoleEnum.CLIENT && order.status === 'PENDING';
  }

  canCreateOrder(): boolean {
    return this.currentRole === RoleEnum.MANAGER || this.currentRole === RoleEnum.CLIENT;
  }

  canCheckFeasibility(): boolean {
    return this.currentRole === RoleEnum.MANAGER || this.currentRole === RoleEnum.DISPECER;
  }

  hasOperationalWarnings(order: OrderResponse): boolean {
    return this.getOperationalWarnings(order).length > 0;
  }

  getOperationalWarnings(order: OrderResponse): string[] {
    return this.orderOperationalWarnings.get(order.id) ?? [];
  }

  getOperationalWarningsTitle(order: OrderResponse): string {
    return this.getOperationalWarnings(order).join('\n');
  }

  displayValue(value: string | number | boolean | null | undefined): string {
    if (value === null || value === undefined || value === '') {
      return 'vehicles.not_available';
    }

    return String(value);
  }

  private lockBackgroundScroll(): void {
    this.document.body.classList.add('modal-scroll-lock');
  }

  private unlockBackgroundScroll(): void {
    this.document.body.classList.remove('modal-scroll-lock');
  }

  private loadOperationalWarnings(orders: OrderResponse[]): void {
    if (!this.canCheckFeasibility()) {
      this.orderOperationalWarnings = new Map<string, string[]>();
      this.changeDetectorRef.detectChanges();
      return;
    }

    const pendingOrders = orders.filter((order) => order.status === 'PENDING');

    if (!pendingOrders.length) {
      this.orderOperationalWarnings = new Map<string, string[]>();
      this.changeDetectorRef.detectChanges();
      return;
    }

    forkJoin(
      pendingOrders.map((order) =>
        this.orderService
          .getOrderOperationalWarnings(order.id)
          .pipe(catchError(() => of({ is_feasible: true, warnings: [] }))),
      ),
    ).subscribe((results) => {
      const warnings = new Map<string, string[]>();

      results.forEach((result, index) => {
        if (result.warnings.length) {
          warnings.set(pendingOrders[index].id, result.warnings);
        }
      });

      this.orderOperationalWarnings = warnings;
      this.changeDetectorRef.detectChanges();
    });
  }
}
