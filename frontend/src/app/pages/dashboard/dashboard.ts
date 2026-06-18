import { ChangeDetectorRef, Component, Inject, OnDestroy } from '@angular/core';
import { CommonModule, DOCUMENT } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';

import { AuthService, RoleEnum } from '../../core/services/auth';
import {
  ServiceTimeConfigResponse,
  SystemConfigService,
  UpdateServiceTimeConfigRequest,
} from '../../core/services/system-config';
import { TranslatePipe } from '../../core/pipes/translate';

interface Metric {
  label: string;
  value: string;
  trend: string;
}

interface DashboardItem {
  id: string;
  title: string;
  status: string;
  meta: string;
}

interface RoleDashboard {
  eyebrow: string;
  title: string;
  description: string;
  primaryPanelTitle: string;
  primaryPanelMeta: string;
  activityTitle: string;
  activityMeta: string;
  metrics: Metric[];
  items: DashboardItem[];
  activities: string[];
  actions: string[];
}

interface ServiceTimeRow {
  key: keyof ServiceTimeConfigResponse;
  label: string;
  value: number;
}

interface ServiceTimeGroup {
  title: string;
  rows: ServiceTimeRow[];
}

const ROLE_DASHBOARDS: Record<RoleEnum, RoleDashboard> = {
  [RoleEnum.SUPER_ADMIN]: {
    eyebrow: 'dashboard.super.eyebrow',
    title: 'dashboard.super.title',
    description: 'dashboard.super.description',
    primaryPanelTitle: 'dashboard.panel.companies_attention',
    primaryPanelMeta: 'dashboard.meta.all_tenants',
    activityTitle: 'dashboard.panel.platform_activity',
    activityMeta: 'dashboard.meta.live',
    metrics: [
      { label: 'Active companies', value: '18', trend: '+2 this month' },
      { label: 'Managers', value: '42', trend: '3 pending invites' },
      { label: 'Platform orders', value: '1.8k', trend: '+14% weekly' },
      { label: 'Disabled companies', value: '2', trend: 'Review required' },
    ],
    items: [
      { id: 'CMP-014', title: 'Rapid Logistics', status: 'Active', meta: '246 orders this week' },
      { id: 'CMP-009', title: 'Nord Cargo', status: 'Payment review', meta: 'Manager access limited' },
      { id: 'CMP-003', title: 'Blue Fleet', status: 'Setup pending', meta: 'No manager assigned' },
    ],
    activities: [
      'Created manager account for Rapid Logistics',
      'Updated global route planning configuration',
      'Deactivated inactive tenant Delta Trans',
      'Reviewed platform usage for 18 companies',
    ],
    actions: [
      'dashboard.action.create_company',
      'dashboard.action.invite_manager',
      'dashboard.action.review_usage',
      'dashboard.action.configure_platform',
    ],
  },
  [RoleEnum.MANAGER]: {
    eyebrow: 'dashboard.manager.eyebrow',
    title: 'dashboard.manager.title',
    description: 'dashboard.manager.description',
    primaryPanelTitle: 'dashboard.panel.company_shipments',
    primaryPanelMeta: 'dashboard.meta.today',
    activityTitle: 'dashboard.panel.team_activity',
    activityMeta: 'dashboard.meta.live',
    metrics: [
      { label: 'Active orders', value: '128', trend: '+12 today' },
      { label: 'Vehicles available', value: '26', trend: '8 in service' },
      { label: 'Drivers approved', value: '52', trend: '4 pending approval' },
      { label: 'Open incidents', value: '5', trend: '2 high priority' },
    ],
    items: [
      { id: 'ORD-1048', title: 'Bucharest -> Cluj-Napoca', status: 'In transit', meta: 'ETA 14:35' },
      { id: 'ORD-1047', title: 'Brasov -> Timisoara', status: 'Loading', meta: 'ETA 16:10' },
      { id: 'ORD-1046', title: 'Iasi -> Constanta', status: 'Planned', meta: 'ETA Tomorrow' },
    ],
    activities: [
      'Approved client account for Premium Retail',
      'Assigned vehicle B-742-TMS to Trip 209',
      'Dispatcher generated a route plan for 18 deliveries',
      'Driver approval pending for Mihai Popescu',
    ],
    actions: [
      'dashboard.action.invite_user',
      'dashboard.action.approve_clients',
      'dashboard.action.manage_fleet',
      'dashboard.action.review_incidents',
    ],
  },
  [RoleEnum.DISPECER]: {
    eyebrow: 'dashboard.dispatcher.eyebrow',
    title: 'dashboard.dispatcher.title',
    description: 'dashboard.dispatcher.description',
    primaryPanelTitle: 'dashboard.panel.trips_dispatch',
    primaryPanelMeta: 'dashboard.meta.next_24h',
    activityTitle: 'dashboard.panel.planning_queue',
    activityMeta: 'dashboard.meta.active',
    metrics: [
      { label: 'Trips planned', value: '19', trend: '6 need assignment' },
      { label: 'Orders queued', value: '87', trend: '23 unplanned' },
      { label: 'Vehicles en route', value: '34', trend: '7 delayed' },
      { label: 'Route changes', value: '11', trend: 'Today' },
    ],
    items: [
      { id: 'TRP-209', title: 'North region deliveries', status: 'Needs driver', meta: '18 stops' },
      { id: 'TRP-210', title: 'Bucharest local route', status: 'Ready', meta: '9 stops' },
      { id: 'TRP-211', title: 'West hub transfer', status: 'Replan', meta: 'Traffic delay' },
    ],
    activities: [
      'Route optimization completed for TRP-210',
      'Vehicle B-742-TMS reported a 24 minute delay',
      'Order ORD-1049 moved to tomorrow',
      'Driver confirmed loading for TRP-206',
    ],
    actions: [
      'dashboard.action.generate_plan',
      'dashboard.action.assign_vehicle',
      'dashboard.action.replan_route',
      'dashboard.action.view_map',
    ],
  },
  [RoleEnum.SOFER]: {
    eyebrow: 'dashboard.driver.eyebrow',
    title: 'dashboard.driver.title',
    description: 'dashboard.driver.description',
    primaryPanelTitle: 'dashboard.panel.assigned_stops',
    primaryPanelMeta: 'dashboard.meta.current_trip',
    activityTitle: 'dashboard.panel.trip_updates',
    activityMeta: 'dashboard.meta.today',
    metrics: [
      { label: 'Stops today', value: '9', trend: '4 completed' },
      { label: 'Distance left', value: '186 km', trend: 'On schedule' },
      { label: 'Incidents', value: '1', trend: 'Reported' },
      { label: 'Next stop', value: '14:35', trend: 'Cluj-Napoca' },
    ],
    items: [
      { id: 'STOP-04', title: 'Retail Park Cluj', status: 'Next', meta: 'ETA 14:35' },
      { id: 'STOP-05', title: 'Central Warehouse', status: 'Pending', meta: '2 pallets' },
      { id: 'STOP-06', title: 'Client pickup point', status: 'Pending', meta: 'Signature required' },
    ],
    activities: [
      'Confirmed delivery at STOP-03',
      'Reported loading delay at Brasov hub',
      'Dispatcher updated sequence for remaining stops',
      'Proof of delivery uploaded for ORD-1042',
    ],
    actions: [
      'dashboard.action.start_stop',
      'dashboard.action.mark_delivered',
      'dashboard.action.report_incident',
      'dashboard.action.call_dispatcher',
    ],
  },
  [RoleEnum.CLIENT]: {
    eyebrow: 'dashboard.client.eyebrow',
    title: 'dashboard.client.title',
    description: 'dashboard.client.description',
    primaryPanelTitle: 'dashboard.panel.my_orders',
    primaryPanelMeta: 'dashboard.meta.recent',
    activityTitle: 'dashboard.panel.order_updates',
    activityMeta: 'dashboard.meta.latest',
    metrics: [
      { label: 'Open orders', value: '12', trend: '3 in transit' },
      { label: 'Delivered this month', value: '48', trend: '+8 vs last month' },
      { label: 'Pending quotes', value: '2', trend: 'Awaiting review' },
      { label: 'Issues', value: '1', trend: 'Carrier response pending' },
    ],
    items: [
      { id: 'ORD-1048', title: 'Bucharest -> Cluj-Napoca', status: 'In transit', meta: 'ETA 14:35' },
      { id: 'ORD-1039', title: 'Warehouse pickup', status: 'Awaiting pickup', meta: 'Tomorrow' },
      { id: 'ORD-1028', title: 'Return shipment', status: 'Delivered', meta: 'Yesterday' },
    ],
    activities: [
      'ORD-1048 departed from Brasov checkpoint',
      'Quote request accepted for express shipment',
      'Delivery proof available for ORD-1028',
      'Carrier asked for updated pickup contact',
    ],
    actions: [
      'dashboard.action.create_order',
      'dashboard.action.track_shipment',
      'dashboard.action.request_quote',
      'dashboard.action.view_invoices',
    ],
  },
  [RoleEnum.GUEST]: {
    eyebrow: 'dashboard.guest.eyebrow',
    title: 'dashboard.guest.title',
    description: 'dashboard.guest.description',
    primaryPanelTitle: 'dashboard.panel.example_orders',
    primaryPanelMeta: 'dashboard.meta.demo',
    activityTitle: 'dashboard.panel.example_activity',
    activityMeta: 'dashboard.meta.demo',
    metrics: [
      { label: 'Open orders', value: '12', trend: 'Demo data' },
      { label: 'Vehicles en route', value: '8', trend: 'Demo data' },
      { label: 'Users online', value: '24', trend: 'Demo data' },
      { label: 'Incidents', value: '1', trend: 'Demo data' },
    ],
    items: [
      { id: 'ORD-1001', title: 'Bucharest -> Cluj-Napoca', status: 'In transit', meta: 'Example' },
      { id: 'ORD-1002', title: 'Brasov -> Timisoara', status: 'Loading', meta: 'Example' },
      { id: 'ORD-1003', title: 'Iasi -> Constanta', status: 'Planned', meta: 'Example' },
    ],
    activities: [
      'Example route plan generated',
      'Example driver assignment updated',
      'Example delivery status changed',
      'Example incident reported',
    ],
    actions: [
      'dashboard.action.sign_in',
      'dashboard.action.create_account',
      'dashboard.action.view_demo',
    ],
  },
};

@Component({
  selector: 'app-dashboard',
  imports: [CommonModule, TranslatePipe],
  templateUrl: './dashboard.html',
  styleUrl: './dashboard.scss',
})
export class Dashboard implements OnDestroy {
  currentRole: RoleEnum;
  roleLabel: string;
  dashboard: RoleDashboard;
  isServiceTimeWindowOpen = false;
  isLoadingServiceTimes = false;
  isSavingServiceTimes = false;
  serviceTimeError = '';
  serviceTimeSuccess = '';
  serviceTimeConfig: ServiceTimeConfigResponse | null = null;
  originalServiceTimeConfig: ServiceTimeConfigResponse | null = null;
  serviceTimeGroups: ServiceTimeGroup[] = [];

  constructor(
    private authService: AuthService,
    private systemConfigService: SystemConfigService,
    private changeDetectorRef: ChangeDetectorRef,
    @Inject(DOCUMENT) private document: Document,
  ) {
    this.currentRole = this.authService.getCurrentRole();
    this.roleLabel = `dashboard.role.${this.currentRole}`;
    this.dashboard = ROLE_DASHBOARDS[this.currentRole];
  }

  ngOnDestroy(): void {
    this.unlockBackgroundScroll();
  }

  get isManager(): boolean {
    return this.currentRole === RoleEnum.MANAGER;
  }

  openServiceTimeWindow(): void {
    if (!this.isManager) {
      return;
    }

    this.isServiceTimeWindowOpen = true;
    this.serviceTimeError = '';
    this.serviceTimeSuccess = '';
    this.serviceTimeConfig = null;
    this.originalServiceTimeConfig = null;
    this.serviceTimeGroups = [];
    this.loadServiceTimes();
    this.lockBackgroundScroll();
    this.changeDetectorRef.detectChanges();
  }

  closeServiceTimeWindow(): void {
    this.isServiceTimeWindowOpen = false;
    this.isLoadingServiceTimes = false;
    this.isSavingServiceTimes = false;
    this.serviceTimeError = '';
    this.serviceTimeSuccess = '';
    this.serviceTimeConfig = null;
    this.originalServiceTimeConfig = null;
    this.serviceTimeGroups = [];
    this.unlockBackgroundScroll();
    this.changeDetectorRef.detectChanges();
  }

  private loadServiceTimes(): void {
    this.isLoadingServiceTimes = true;
    this.serviceTimeError = '';
    this.serviceTimeSuccess = '';
    this.changeDetectorRef.detectChanges();

    this.systemConfigService.getServiceTimeConfig().subscribe({
      next: (config) => {
        this.serviceTimeConfig = { ...config };
        this.originalServiceTimeConfig = { ...config };
        this.serviceTimeGroups = this.buildServiceTimeGroups(config);
        this.isLoadingServiceTimes = false;
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.serviceTimeError = error.error?.detail ?? 'common.error_generic';
        this.isLoadingServiceTimes = false;
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  updateServiceTimeValue(key: keyof ServiceTimeConfigResponse, value: string): void {
    if (!this.serviceTimeConfig) {
      return;
    }

    const parsedValue = Number(value);
    this.serviceTimeConfig = {
      ...this.serviceTimeConfig,
      [key]: Number.isFinite(parsedValue) ? parsedValue : 0,
    };
    this.serviceTimeGroups = this.buildServiceTimeGroups(this.serviceTimeConfig);
    this.serviceTimeError = '';
    this.serviceTimeSuccess = '';
    this.changeDetectorRef.detectChanges();
  }

  hasServiceTimeChanges(): boolean {
    const current = this.serviceTimeConfig;
    const original = this.originalServiceTimeConfig;

    if (!current || !original) {
      return false;
    }

    return (Object.keys(current) as Array<keyof ServiceTimeConfigResponse>).some(
      (key) => current[key] !== original[key],
    );
  }

  saveServiceTimes(): void {
    if (!this.serviceTimeConfig || !this.hasServiceTimeChanges()) {
      return;
    }

    this.isSavingServiceTimes = true;
    this.serviceTimeError = '';
    this.serviceTimeSuccess = '';
    this.changeDetectorRef.detectChanges();

    const payload: UpdateServiceTimeConfigRequest = { ...this.serviceTimeConfig };

    this.systemConfigService.updateServiceTimeConfig(payload).subscribe({
      next: (config) => {
        this.serviceTimeConfig = { ...config };
        this.originalServiceTimeConfig = { ...config };
        this.serviceTimeGroups = this.buildServiceTimeGroups(config);
        this.isSavingServiceTimes = false;
        this.serviceTimeSuccess = 'dashboard.service_time.save_success';
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.serviceTimeError = error.error?.detail ?? 'common.error_generic';
        this.isSavingServiceTimes = false;
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  private buildServiceTimeGroups(config: ServiceTimeConfigResponse): ServiceTimeGroup[] {
    const rows: ServiceTimeRow[] = [
      { key: 'standard_pickup_service_min', label: 'dashboard.service_time.standard_pickup', value: config.standard_pickup_service_min },
      { key: 'standard_delivery_service_min', label: 'dashboard.service_time.standard_delivery', value: config.standard_delivery_service_min },
      { key: 'fragil_pickup_service_min', label: 'dashboard.service_time.fragile_pickup', value: config.fragil_pickup_service_min },
      { key: 'fragil_delivery_service_min', label: 'dashboard.service_time.fragile_delivery', value: config.fragil_delivery_service_min },
      { key: 'perisabil_pickup_service_min', label: 'dashboard.service_time.perishable_pickup', value: config.perisabil_pickup_service_min },
      { key: 'perisabil_delivery_service_min', label: 'dashboard.service_time.perishable_delivery', value: config.perisabil_delivery_service_min },
      { key: 'adr_pickup_service_min', label: 'dashboard.service_time.adr_pickup', value: config.adr_pickup_service_min },
      { key: 'adr_delivery_service_min', label: 'dashboard.service_time.adr_delivery', value: config.adr_delivery_service_min },
      { key: 'service_extra_minutes_per_500kg', label: 'dashboard.service_time.extra_kg', value: config.service_extra_minutes_per_500kg },
      { key: 'service_extra_minutes_per_5m3', label: 'dashboard.service_time.extra_m3', value: config.service_extra_minutes_per_5m3 },
      { key: 'service_max_minutes', label: 'dashboard.service_time.max_minutes', value: config.service_max_minutes },
    ];

    return [
      {
        title: 'dashboard.service_time.base_group',
        rows: rows.slice(0, 8),
      },
      {
        title: 'dashboard.service_time.adjustments_group',
        rows: rows.slice(8),
      },
    ];
  }

  private lockBackgroundScroll(): void {
    this.document.body.classList.add('modal-scroll-lock');
  }

  private unlockBackgroundScroll(): void {
    this.document.body.classList.remove('modal-scroll-lock');
  }
}
