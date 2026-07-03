import { Component, HostListener, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import {
  AnalyticsService,
  ZoneDemandResponse,
  FleetUtilizationResponse,
  FleetUtilizationTripItem,
  PlanVsActualResponse,
  CostAnalyticsResponse,
  IncidentImpactResponse,
} from '../../core/services/analytics';
import { I18nService } from '../../core/services/i18n';
import { TranslatePipe } from '../../core/pipes/translate';

@Component({
  selector: 'app-analytics',
  imports: [CommonModule, FormsModule, TranslatePipe],
  templateUrl: './analytics.html',
  styleUrl: './analytics.scss',
})
export class Analytics implements OnInit {
  protected readonly zoneDemand = signal<ZoneDemandResponse | null>(null);
  protected readonly fleetUtilization = signal<FleetUtilizationResponse | null>(null);
  protected readonly planVsActual = signal<PlanVsActualResponse | null>(null);
  protected readonly costs = signal<CostAnalyticsResponse | null>(null);
  protected readonly incidentImpact = signal<IncidentImpactResponse | null>(null);
  protected readonly selectedTrip = signal<FleetUtilizationTripItem | null>(null);

  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);

  protected readonly startDate = signal<string>('');
  protected readonly endDate = signal<string>('');

  protected readonly selectedTab = signal<'overview' | 'zones' | 'fleet' | 'plan-vs-actual' | 'costs' | 'incidents'>('overview');

  constructor(
    private analyticsService: AnalyticsService,
    private i18n: I18nService,
  ) {
    this.initializeDateRange();
  }

  ngOnInit(): void {
    this.loadAnalytics();
  }

  private initializeDateRange(): void {
    const today = new Date();
    const thirtyDaysAgo = new Date(today.getTime() - 30 * 24 * 60 * 60 * 1000);

    this.endDate.set(this.formatDate(today));
    this.startDate.set(this.formatDate(thirtyDaysAgo));
  }

  private formatDate(date: Date): string {
    return date.toISOString().split('T')[0];
  }

  protected loadAnalytics(): void {
    this.loading.set(true);
    this.error.set(null);

    const start = this.startDate();
    const end = this.endDate();

    Promise.all([
      this.analyticsService.getZoneDemand(start, end).toPromise(),
      this.analyticsService.getFleetUtilization(start, end).toPromise(),
      this.analyticsService.getPlanVsActual(start, end).toPromise(),
      this.analyticsService.getCosts(start, end).toPromise(),
      this.analyticsService.getIncidentImpact(start, end).toPromise(),
    ])
      .then(([zone, fleet, planVsActual, costs, incidentImpact]) => {
        if (zone) this.zoneDemand.set(zone);
        if (fleet) this.fleetUtilization.set(fleet);
        if (planVsActual) this.planVsActual.set(planVsActual);
        if (costs) this.costs.set(costs);
        if (incidentImpact) this.incidentImpact.set(incidentImpact);
        this.loading.set(false);
      })
      .catch((err) => {
        this.error.set(this.i18n.translate('analytics.error_load'));
        this.loading.set(false);
      });
  }

  protected selectTab(tab: 'overview' | 'zones' | 'fleet' | 'plan-vs-actual' | 'costs' | 'incidents'): void {
    this.selectedTab.set(tab);
  }

  protected openTripDetails(trip: FleetUtilizationTripItem): void {
    this.selectedTrip.set(trip);
  }

  protected closeTripDetails(): void {
    this.selectedTrip.set(null);
  }

  @HostListener('document:keydown.escape')
  protected closeTripDetailsOnEscape(): void {
    this.closeTripDetails();
  }

  protected getQualityColor(score: number): string {
    if (score >= 70) return 'var(--color-success)';
    if (score >= 40) return 'var(--color-warning)';
    return 'var(--color-danger)';
  }

  protected getDemandColor(level: string): string {
    switch (level) {
      case 'HIGH':
        return 'var(--color-danger)';
      case 'MEDIUM':
        return 'var(--color-warning)';
      case 'LOW':
        return 'var(--color-success)';
      default:
        return 'var(--color-secondary)';
    }
  }

  protected formatCurrency(value: number | null | undefined): string {
    if (value === null || value === undefined) return '-';
    return `${value.toFixed(2)} RON`;
  }

  protected formatPercentage(value: number | null | undefined): string {
    if (value === null || value === undefined) return '-';
    return `${value.toFixed(1)}%`;
  }

  protected formatNumber(value: number | null | undefined, decimals: number = 0): string {
    if (value === null || value === undefined) return '-';
    return value.toFixed(decimals);
  }
}
