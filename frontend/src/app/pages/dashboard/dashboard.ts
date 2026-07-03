import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';

import { AuthService, RoleEnum } from '../../core/services/auth';
import { Icon } from '../../shared/icon/icon';
import {
  AttentionItem,
  ChartPoint,
  DashboardService,
  DispatcherDashboardData,
  DriverWorkload,
  ManagerDashboardData,
  ManagerKpi,
  ManagerPeriod,
  StatusSlice,
  SuperAdminKpiSection,
  TripSummary,
} from '../../core/services/dashboard';
import { TranslatePipe } from '../../core/pipes/translate';
import { OrderResponse, OrderService } from '../../core/services/order';
import { I18nService, Language } from '../../core/services/i18n';

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

const MANAGER_DASHBOARD_DATA: Record<ManagerPeriod, ManagerDashboardData> = {
  1: {
    kpis: [
      { label: 'Orders today', value: '42', detail: '+8 since morning', tone: 'good' },
      { label: 'Delivery success', value: '94%', detail: '31 delivered, 2 failed', tone: 'good' },
      { label: 'Active trips', value: '11', detail: '7 in progress', tone: 'neutral' },
      { label: 'Open incidents', value: '3', detail: '1 major unresolved', tone: 'warn' },
      { label: 'Fleet available', value: '68%', detail: '19 of 28 vehicles', tone: 'neutral' },
    ],
    orderTrend: [
      { label: '08:00', value: 5 },
      { label: '10:00', value: 9 },
      { label: '12:00', value: 14 },
      { label: '14:00', value: 21 },
      { label: '16:00', value: 31 },
      { label: '18:00', value: 42 },
    ],
    orderStatus: [
      { label: 'Pending', value: 8, color: '#f59e0b' },
      { label: 'Planned', value: 10, color: '#2563eb' },
      { label: 'In delivery', value: 13, color: '#7c3aed' },
      { label: 'Delivered', value: 31, color: '#16a34a' },
      { label: 'Failed', value: 2, color: '#dc2626' },
    ],
    tripStatus: [
      { label: 'Approved', value: 4 },
      { label: 'In progress', value: 7 },
      { label: 'Completed', value: 9 },
      { label: 'Interrupted', value: 1 },
    ],
    fleetStatus: [
      { label: 'Available', value: 19 },
      { label: 'Reserved', value: 5 },
      { label: 'Service', value: 3 },
      { label: 'Damaged', value: 1 },
    ],
    driverStatus: [
      { label: 'Available', value: 16 },
      { label: 'On trip', value: 12 },
      { label: 'Break', value: 4 },
      { label: 'Off duty', value: 8 },
    ],
    driverWorkload: [
      { driver: 'Mihai Popescu', trips: 3, stops: 21 },
      { driver: 'Andrei Ionescu', trips: 2, stops: 18 },
      { driver: 'Elena Radu', trips: 2, stops: 15 },
      { driver: 'Vlad Marin', trips: 1, stops: 11 },
    ],
    attention: [
      { title: 'TRP-209 delayed', detail: 'ETA slipped by 34 minutes near Brasov.', severity: 'High' },
      { title: 'Vehicle B-742-TMS in service', detail: 'Replacement needed for tomorrow route.', severity: 'Medium' },
      { title: '2 failed delivery stops', detail: 'Wrong address and refused delivery.', severity: 'Medium' },
    ],
    todayTrips: [
      { id: 'TRP-209', driver: 'Mihai Popescu', route: 'Bucharest -> Cluj', progress: 68, status: 'In progress' },
      { id: 'TRP-210', driver: 'Elena Radu', route: 'Brasov local', progress: 41, status: 'In progress' },
      { id: 'TRP-211', driver: 'Andrei Ionescu', route: 'Timisoara hub', progress: 100, status: 'Completed' },
    ],
  },
  7: {
    kpis: [
      { label: 'Orders', value: '318', detail: '+12% vs previous week', tone: 'good' },
      { label: 'Delivery success', value: '91%', detail: '268 delivered, 18 failed', tone: 'good' },
      { label: 'Active trips', value: '64', detail: '44 completed this week', tone: 'neutral' },
      { label: 'Open incidents', value: '9', detail: '3 major unresolved', tone: 'warn' },
      { label: 'Cost variance', value: '+7.4%', detail: 'Fuel and extra cost pressure', tone: 'warn' },
    ],
    orderTrend: [
      { label: 'Mon', value: 38 },
      { label: 'Tue', value: 46 },
      { label: 'Wed', value: 51 },
      { label: 'Thu', value: 44 },
      { label: 'Fri', value: 57 },
      { label: 'Sat', value: 39 },
      { label: 'Sun', value: 43 },
    ],
    orderStatus: [
      { label: 'Pending', value: 42, color: '#f59e0b' },
      { label: 'Planned', value: 55, color: '#2563eb' },
      { label: 'In delivery', value: 38, color: '#7c3aed' },
      { label: 'Delivered', value: 268, color: '#16a34a' },
      { label: 'Failed', value: 18, color: '#dc2626' },
      { label: 'Cancelled', value: 7, color: '#64748b' },
    ],
    tripStatus: [
      { label: 'Proposed', value: 9 },
      { label: 'Approved', value: 11 },
      { label: 'In progress', value: 8 },
      { label: 'Completed', value: 44 },
      { label: 'Interrupted', value: 3 },
    ],
    fleetStatus: [
      { label: 'Available', value: 21 },
      { label: 'Reserved', value: 4 },
      { label: 'Service', value: 2 },
      { label: 'Damaged', value: 1 },
    ],
    driverStatus: [
      { label: 'Available', value: 18 },
      { label: 'On trip', value: 10 },
      { label: 'Break', value: 5 },
      { label: 'Off duty', value: 7 },
    ],
    driverWorkload: [
      { driver: 'Mihai Popescu', trips: 12, stops: 86 },
      { driver: 'Andrei Ionescu', trips: 10, stops: 74 },
      { driver: 'Elena Radu', trips: 9, stops: 69 },
      { driver: 'Vlad Marin', trips: 8, stops: 61 },
    ],
    attention: [
      { title: '3 unresolved major incidents', detail: 'Two vehicle issues and one route interruption.', severity: 'High' },
      { title: '18 failed orders', detail: 'Failure rate above weekly target by 1.8%.', severity: 'Medium' },
      { title: 'Fuel cost variance +9%', detail: 'Actual fuel spend exceeded plan on long routes.', severity: 'Medium' },
    ],
    todayTrips: [
      { id: 'TRP-244', driver: 'Mihai Popescu', route: 'North region deliveries', progress: 75, status: 'In progress' },
      { id: 'TRP-246', driver: 'Vlad Marin', route: 'Bucharest local', progress: 52, status: 'In progress' },
      { id: 'TRP-247', driver: 'Elena Radu', route: 'West hub transfer', progress: 18, status: 'Approved' },
    ],
  },
  30: {
    kpis: [
      { label: 'Orders', value: '1,428', detail: '+8.6% vs previous month', tone: 'good' },
      { label: 'Delivery success', value: '89%', detail: '1,173 delivered, 92 failed', tone: 'warn' },
      { label: 'Trips completed', value: '214', detail: '31 recovery trips', tone: 'neutral' },
      { label: 'Open incidents', value: '17', detail: '5 major unresolved', tone: 'danger' },
      { label: 'Cost variance', value: '+5.9%', detail: 'Actual above plan', tone: 'warn' },
    ],
    orderTrend: [
      { label: 'W1', value: 302 },
      { label: 'W2', value: 347 },
      { label: 'W3', value: 361 },
      { label: 'W4', value: 418 },
    ],
    orderStatus: [
      { label: 'Pending', value: 124, color: '#f59e0b' },
      { label: 'Planned', value: 185, color: '#2563eb' },
      { label: 'In delivery', value: 96, color: '#7c3aed' },
      { label: 'Delivered', value: 1173, color: '#16a34a' },
      { label: 'Failed', value: 92, color: '#dc2626' },
      { label: 'Cancelled', value: 31, color: '#64748b' },
    ],
    tripStatus: [
      { label: 'Proposed', value: 22 },
      { label: 'Approved', value: 34 },
      { label: 'In progress', value: 14 },
      { label: 'Completed', value: 214 },
      { label: 'Interrupted', value: 12 },
      { label: 'Cancelled', value: 8 },
    ],
    fleetStatus: [
      { label: 'Available', value: 20 },
      { label: 'Reserved', value: 5 },
      { label: 'Service', value: 2 },
      { label: 'Damaged', value: 1 },
    ],
    driverStatus: [
      { label: 'Available', value: 17 },
      { label: 'On trip', value: 12 },
      { label: 'Break', value: 3 },
      { label: 'Off duty', value: 8 },
    ],
    driverWorkload: [
      { driver: 'Mihai Popescu', trips: 41, stops: 302 },
      { driver: 'Andrei Ionescu', trips: 37, stops: 284 },
      { driver: 'Elena Radu', trips: 34, stops: 261 },
      { driver: 'Vlad Marin', trips: 29, stops: 226 },
    ],
    attention: [
      { title: 'Delivery success below target', detail: '89% vs 92% monthly target.', severity: 'High' },
      { title: '17 unresolved incidents', detail: 'Major incidents remain open beyond SLA.', severity: 'High' },
      { title: '31 recovery trips', detail: 'Recovery volume suggests planning or address quality issues.', severity: 'Medium' },
    ],
    todayTrips: [
      { id: 'TRP-318', driver: 'Andrei Ionescu', route: 'Cluj -> Oradea', progress: 88, status: 'In progress' },
      { id: 'TRP-320', driver: 'Mihai Popescu', route: 'Bucharest -> Iasi', progress: 63, status: 'In progress' },
      { id: 'TRP-321', driver: 'Elena Radu', route: 'Constanta local', progress: 24, status: 'Approved' },
    ],
  },
};

const SUPER_ADMIN_KPI_SECTIONS: SuperAdminKpiSection[] = [
  {
    title: 'Tenant health',
    description: 'Company activation, setup progress, and platform access.',
    kpis: [
      { label: 'Active companies', value: '18', detail: '2 added this month', tone: 'good' },
      { label: 'Pending setup', value: '3', detail: 'Missing manager or config', tone: 'warn' },
      { label: 'Disabled companies', value: '2', detail: 'Require admin review', tone: 'danger' },
      { label: 'Companies with activity', value: '83%', detail: '15 of 18 active this week', tone: 'neutral' },
    ],
  },
  {
    title: 'Accounts and approvals',
    description: 'User governance across all companies.',
    kpis: [
      { label: 'Total users', value: '426', detail: 'Across all tenants', tone: 'neutral' },
      { label: 'Managers', value: '42', detail: '3 pending invites', tone: 'neutral' },
      { label: 'Pending approvals', value: '17', detail: 'Clients and employees waiting', tone: 'warn' },
      { label: 'Inactive users', value: '31', detail: 'No activity in 30 days', tone: 'warn' },
    ],
  },
  {
    title: 'Platform volume',
    description: 'Cross-tenant transport activity and growth.',
    kpis: [
      { label: 'Orders this month', value: '12.8k', detail: '+14% vs previous month', tone: 'good' },
      { label: 'Trips completed', value: '2,146', detail: 'Platform-wide', tone: 'good' },
      { label: 'Vehicles registered', value: '318', detail: '26 currently in service', tone: 'neutral' },
      { label: 'Drivers registered', value: '504', detail: '438 approved', tone: 'neutral' },
    ],
  },
  {
    title: 'Risk and operations',
    description: 'Issues that need platform-level attention.',
    kpis: [
      { label: 'Open incidents', value: '24', detail: '6 high priority', tone: 'danger' },
      { label: 'Failed deliveries', value: '3.8%', detail: 'Last 30 days', tone: 'warn' },
      { label: 'Password reset requests', value: '39', detail: 'Requested in last 30 days', tone: 'neutral' },
    ],
  },
];

const DISPATCHER_DASHBOARD_DATA: DispatcherDashboardData = {
  kpis: [
    { label: 'Ongoing trips', value: '7', detail: '42 stops in execution', tone: 'neutral' },
    { label: 'Orders to be planned', value: '23', detail: 'Pending orders without assigned delivery date', tone: 'warn' },
    { label: 'Need attention', value: '9', detail: 'Orders, trips, stops, and incidents', tone: 'warn' },
    { label: 'Unassigned trips', value: '4', detail: 'Missing driver or vehicle', tone: 'warn' },
    { label: 'Available drivers', value: '16', detail: '40 total drivers', tone: 'good' },
    { label: 'Available vehicles', value: '19', detail: '28 total vehicles', tone: 'good' },
    { label: 'Planning sessions', value: '2', detail: 'Draft or proposed plans', tone: 'neutral' },
  ],
  ongoingTrips: [
    { id: 'TRP-209', driver: 'Mihai Popescu', route: 'Bucharest -> Cluj', progress: 68, status: 'In Progress' },
    { id: 'TRP-210', driver: 'Elena Radu', route: 'Brasov local', progress: 41, status: 'In Progress' },
  ],
  attention: [
    { title: '2 trips missing driver or vehicle', detail: 'Trips cannot be executed until driver and vehicle are assigned.', severity: 'Medium' },
    { title: '3 problematic orders', detail: 'Orders were marked problematic and need review before planning.', severity: 'Medium' },
    { title: '1 interrupted trip', detail: 'Interrupted trips may need recovery planning.', severity: 'High' },
  ],
};

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
  imports: [CommonModule, TranslatePipe, RouterLink, Icon],
  templateUrl: './dashboard.html',
  styleUrl: './dashboard.scss',
})
export class Dashboard implements OnInit {
  readonly periodOptions: ManagerPeriod[] = [1, 7, 30];

  currentRole: RoleEnum;
  roleLabel: string;
  dashboard: RoleDashboard;
  selectedPeriod: ManagerPeriod = 7;
  managerDashboardData: ManagerDashboardData = MANAGER_DASHBOARD_DATA[this.selectedPeriod];
  superAdminDashboardSections: SuperAdminKpiSection[] = SUPER_ADMIN_KPI_SECTIONS;
  dispatcherDashboardData: DispatcherDashboardData = DISPATCHER_DASHBOARD_DATA;
  isLoadingManagerDashboard = false;
  isLoadingSuperAdminDashboard = false;
  isLoadingDispatcherDashboard = false;
  clientOrders: OrderResponse[] = [];
  isLoadingClientDashboard = false;
  clientDashboardError = '';

  constructor(
    private authService: AuthService,
    private dashboardService: DashboardService,
    private orderService: OrderService,
    private i18nService: I18nService,
    private changeDetectorRef: ChangeDetectorRef,
  ) {
    this.currentRole = this.authService.getCurrentRole();
    this.roleLabel = `dashboard.role.${this.currentRole}`;
    this.dashboard = ROLE_DASHBOARDS[this.currentRole];
  }

  ngOnInit(): void {
    if (this.isManagerDashboard) {
      this.loadManagerDashboard();
    } else if (this.isSuperAdminDashboard) {
      this.loadSuperAdminDashboard();
    } else if (this.isDispatcherDashboard) {
      this.loadDispatcherDashboard();
    } else if (this.isClientDashboard) {
      this.loadClientDashboard();
    }
  }

  get isManagerDashboard(): boolean {
    return this.currentRole === RoleEnum.MANAGER;
  }

  get isSuperAdminDashboard(): boolean {
    return this.currentRole === RoleEnum.SUPER_ADMIN;
  }

  get isDispatcherDashboard(): boolean {
    return this.currentRole === RoleEnum.DISPECER;
  }

  get isClientDashboard(): boolean {
    return this.currentRole === RoleEnum.CLIENT;
  }

  get clientRecentOrders(): OrderResponse[] {
    return [...this.clientOrders]
      .sort((left, right) => this.orderTimestamp(right) - this.orderTimestamp(left))
      .slice(0, 5);
  }

  get clientActiveOrders(): number {
    return this.clientOrders.filter((order) =>
      ['PENDING', 'PLANNED', 'IN_DELIVERY'].includes(order.status),
    ).length;
  }

  get clientInDeliveryOrders(): number {
    return this.clientOrders.filter((order) => order.status === 'IN_DELIVERY').length;
  }

  get clientDeliveredOrders(): number {
    return this.clientOrders.filter((order) => order.status === 'DELIVERED').length;
  }

  get clientAttentionOrders(): number {
    return this.clientOrders.filter(
      (order) => order.status === 'FAILED' || Boolean(order.is_problematic),
    ).length;
  }

  get clientNextDelivery(): OrderResponse | null {
    return (
      [...this.clientOrders]
        .filter((order) => ['PENDING', 'PLANNED', 'IN_DELIVERY'].includes(order.status))
        .sort((left, right) => left.delivery_deadline.localeCompare(right.delivery_deadline))[0] ??
      null
    );
  }

  get clientDeliveryProgress(): number {
    const order = this.clientNextDelivery;
    return order ? this.orderProgress(order.status) : 0;
  }

  get managerData(): ManagerDashboardData {
    return this.managerDashboardData;
  }

  get superAdminData(): SuperAdminKpiSection[] {
    return this.superAdminDashboardSections;
  }

  get dispatcherData(): DispatcherDashboardData {
    return this.dispatcherDashboardData;
  }

  get maxOrderTrendValue(): number {
    return Math.max(...this.managerData.orderTrend.map((point) => point.value), 1);
  }

  get maxTripStatusValue(): number {
    return Math.max(...this.managerData.tripStatus.map((point) => point.value), 1);
  }

  get maxFleetStatusValue(): number {
    return Math.max(...this.managerData.fleetStatus.map((point) => point.value), 1);
  }

  get maxDriverStatusValue(): number {
    return Math.max(...this.managerData.driverStatus.map((point) => point.value), 1);
  }

  get maxDriverTrips(): number {
    return Math.max(...this.managerData.driverWorkload.map((driver) => driver.trips), 1);
  }

  get orderStatusTotal(): number {
    return this.managerData.orderStatus.reduce((sum, item) => sum + item.value, 0);
  }

  get orderStatusDonut(): string {
    let cursor = 0;
    const total = Math.max(this.orderStatusTotal, 1);
    const segments = this.managerData.orderStatus.map((item) => {
      const start = cursor;
      cursor += (item.value / total) * 100;
      return `${item.color} ${start}% ${cursor}%`;
    });

    return `conic-gradient(${segments.join(', ')})`;
  }

  selectPeriod(period: ManagerPeriod): void {
    this.selectedPeriod = period;
    this.managerDashboardData = MANAGER_DASHBOARD_DATA[period];
    this.loadManagerDashboard();
  }

  barHeight(value: number, max: number): string {
    return `${Math.max((value / max) * 100, 6)}%`;
  }

  barWidth(value: number, max: number): string {
    return `${Math.max((value / max) * 100, 4)}%`;
  }

  periodLabel(period: ManagerPeriod): string {
    return period === 1 ? 'Last 1 day' : `Last ${period} days`;
  }

  orderProgress(status: string): number {
    const progress: Record<string, number> = {
      PENDING: 18,
      PLANNED: 45,
      IN_DELIVERY: 76,
      DELIVERED: 100,
      FAILED: 100,
      CANCELLED: 100,
    };

    return progress[status] ?? 0;
  }

  orderStatusKey(status: string): string {
    return `orders.status.${status.toLowerCase()}`;
  }

  orderStatusClass(status: string): string {
    return `client-status client-status--${status.toLowerCase().replaceAll('_', '-')}`;
  }

  orderRoute(order: OrderResponse): string {
    return `${order.pickup_city || this.shortAddress(order.address_pickup)} -> ${
      order.delivery_city || this.shortAddress(order.address_delivery)
    }`;
  }

  formatClientDate(value: string): string {
    const localeByLanguage: Record<Language, string> = {
      [Language.EN]: 'en-GB',
      [Language.RO]: 'ro-RO',
      [Language.HU]: 'hu-HU',
    };
    const date = new Date(`${value}T12:00:00`);

    return new Intl.DateTimeFormat(localeByLanguage[this.i18nService.currentLanguage], {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
    }).format(date);
  }

  private shortAddress(value: string): string {
    const parts = value
      .split(',')
      .map((part) => part.trim())
      .filter(Boolean);
    return parts.length > 1 ? parts[parts.length - 1] : value;
  }

  private orderTimestamp(order: OrderResponse): number {
    return order.created_at ? new Date(order.created_at).getTime() : 0;
  }

  private loadManagerDashboard(): void {
    this.isLoadingManagerDashboard = true;
    this.changeDetectorRef.detectChanges();

    this.dashboardService.getManagerDashboard(this.selectedPeriod).subscribe({
      next: (data) => {
        this.managerDashboardData = data;
        this.isLoadingManagerDashboard = false;
        this.changeDetectorRef.detectChanges();
      },
      error: () => {
        this.managerDashboardData = MANAGER_DASHBOARD_DATA[this.selectedPeriod];
        this.isLoadingManagerDashboard = false;
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  private loadSuperAdminDashboard(): void {
    this.isLoadingSuperAdminDashboard = true;
    this.changeDetectorRef.detectChanges();

    this.dashboardService.getSuperAdminDashboard().subscribe({
      next: (data) => {
        this.superAdminDashboardSections = data.sections;
        this.isLoadingSuperAdminDashboard = false;
        this.changeDetectorRef.detectChanges();
      },
      error: () => {
        this.superAdminDashboardSections = SUPER_ADMIN_KPI_SECTIONS;
        this.isLoadingSuperAdminDashboard = false;
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  private loadDispatcherDashboard(): void {
    this.isLoadingDispatcherDashboard = true;
    this.changeDetectorRef.detectChanges();

    this.dashboardService.getDispatcherDashboard().subscribe({
      next: (data) => {
        this.dispatcherDashboardData = data;
        this.isLoadingDispatcherDashboard = false;
        this.changeDetectorRef.detectChanges();
      },
      error: () => {
        this.dispatcherDashboardData = DISPATCHER_DASHBOARD_DATA;
        this.isLoadingDispatcherDashboard = false;
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  loadClientDashboard(): void {
    this.isLoadingClientDashboard = true;
    this.clientDashboardError = '';
    this.changeDetectorRef.detectChanges();

    this.orderService.listOrders().subscribe({
      next: (orders) => {
        this.clientOrders = orders;
        this.isLoadingClientDashboard = false;
        this.changeDetectorRef.detectChanges();
      },
      error: () => {
        this.clientOrders = [];
        this.isLoadingClientDashboard = false;
        this.clientDashboardError = 'dashboard.client.load_error';
        this.changeDetectorRef.detectChanges();
      },
    });
  }
}
