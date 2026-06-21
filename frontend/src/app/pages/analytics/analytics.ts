import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { AnalyticsService, ZoneDemandResponse, FleetUtilizationResponse, PlanVsActualResponse, CostAnalyticsResponse } from '../../core/services/analytics';

@Component({
  selector: 'app-analytics',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './analytics.html',
  styleUrl: './analytics.scss',
})
export class Analytics implements OnInit {
  protected readonly zoneDemand = signal<ZoneDemandResponse | null>(null);
  protected readonly fleetUtilization = signal<FleetUtilizationResponse | null>(null);
  protected readonly planVsActual = signal<PlanVsActualResponse | null>(null);
  protected readonly costs = signal<CostAnalyticsResponse | null>(null);

  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);

  protected readonly startDate = signal<string>('');
  protected readonly endDate = signal<string>('');

  protected readonly selectedTab = signal<'overview' | 'zones' | 'fleet' | 'plan-vs-actual' | 'costs' | 'incidents'>('overview');

  constructor(private analyticsService: AnalyticsService) {
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
    ])
      .then(([zone, fleet, planVsActual, costs]) => {
        if (zone) this.zoneDemand.set(zone);
        if (fleet) this.fleetUtilization.set(fleet);
        if (planVsActual) this.planVsActual.set(planVsActual);
        if (costs) this.costs.set(costs);
        this.loading.set(false);
      })
      .catch((err) => {
        this.error.set('Failed to load analytics data');
        this.loading.set(false);
      });
  }

  protected selectTab(tab: 'overview' | 'zones' | 'fleet' | 'plan-vs-actual' | 'costs' | 'incidents'): void {
    this.selectedTab.set(tab);
  }

  protected getQualityColor(score: number): string {
    if (score >= 70) return '#16a34a';
    if (score >= 40) return '#f59e0b';
    return '#dc2626';
  }

  protected getDemandColor(level: string): string {
    switch (level) {
      case 'HIGH':
        return '#dc2626';
      case 'MEDIUM':
        return '#f59e0b';
      case 'LOW':
        return '#16a34a';
      default:
        return '#6b7280';
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
