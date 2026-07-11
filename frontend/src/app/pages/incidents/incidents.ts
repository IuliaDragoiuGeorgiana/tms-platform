import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';

import { TranslatePipe } from '../../core/pipes/translate';
import {
  ImpactAnalysisResponse,
  IncidentListResponse,
  IncidentRecoveryOptionResponse,
  IncidentService,
  IncidentStatusFilter,
  IncidentTypeFilter,
  RecoverIncidentResponse,
} from '../../core/services/incident';

@Component({
  selector: 'app-incidents',
  imports: [CommonModule, TranslatePipe],
  templateUrl: './incidents.html',
  styleUrl: './incidents.scss',
})
export class Incidents implements OnInit {
  incidents: IncidentListResponse[] = [];
  statusFilter: IncidentStatusFilter = 'open';
  typeFilter: IncidentTypeFilter = '';
  searchTerm = '';
  isLoadingIncidents = false;
  isLoadingImpactAnalysis = false;
  isRecoveringIncident = false;
  loadIncidentsError = '';
  impactAnalysisError = '';
  recoverySuccess = '';
  impactAnalysis: ImpactAnalysisResponse | null = null;
  selectedImpactIncident: IncidentListResponse | null = null;

  constructor(
    private incidentService: IncidentService,
    private changeDetectorRef: ChangeDetectorRef,
  ) {}

  ngOnInit(): void {
    this.loadIncidents();
  }

  get filteredIncidents(): IncidentListResponse[] {
    const query = this.searchTerm.trim().toLowerCase();

    if (!query) {
      return this.incidents;
    }

    return this.incidents.filter((incident) =>
      [
        incident.id,
        incident.trip_id,
        incident.trip_status ?? '',
        incident.driver_name ?? incident.driver_id,
        incident.vehicle_plate ?? incident.vehicle_id,
        incident.vehicle_status ?? '',
        incident.type,
        incident.description,
        incident.created_at,
        incident.resolved_at ?? '',
      ]
        .join(' ')
        .toLowerCase()
        .includes(query),
    );
  }

  loadIncidents(): void {
    this.isLoadingIncidents = true;
    this.loadIncidentsError = '';
    this.changeDetectorRef.detectChanges();

    this.incidentService.listIncidents(this.statusFilter, this.typeFilter).subscribe({
      next: (incidents) => {
        this.incidents = incidents;
        this.isLoadingIncidents = false;
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.loadIncidentsError = error.error?.detail ?? 'common.error_generic';
        this.isLoadingIncidents = false;
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  updateSearch(value: string): void {
    this.searchTerm = value;
  }

  updateStatusFilter(value: string): void {
    this.statusFilter = this.isStatusFilter(value) ? value : 'open';
    this.loadIncidents();
  }

  updateTypeFilter(value: string): void {
    this.typeFilter = this.isTypeFilter(value) ? value : '';
    this.loadIncidents();
  }

  openImpactAnalysis(incident: IncidentListResponse): void {
    if (!this.canAnalyzeIncident(incident)) {
      return;
    }

    this.selectedImpactIncident = incident;
    this.impactAnalysis = null;
    this.impactAnalysisError = '';
    this.recoverySuccess = '';
    this.isLoadingImpactAnalysis = true;
    this.changeDetectorRef.detectChanges();

    this.incidentService.getImpactAnalysis(incident.id).subscribe({
      next: (analysis) => {
        this.impactAnalysis = analysis;
        this.isLoadingImpactAnalysis = false;
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.impactAnalysisError = error.error?.detail ?? 'common.error_generic';
        this.isLoadingImpactAnalysis = false;
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  closeImpactAnalysis(): void {
    this.selectedImpactIncident = null;
    this.impactAnalysis = null;
    this.impactAnalysisError = '';
    this.isLoadingImpactAnalysis = false;
    this.isRecoveringIncident = false;
    this.changeDetectorRef.detectChanges();
  }

  canAnalyzeIncident(incident: IncidentListResponse): boolean {
    return Boolean(
      incident.type === 'MAJOR' &&
        incident.trip_status === 'INTERRUPTED' &&
        !incident.resolved_at &&
        !incident.recovery_trip_id,
    );
  }

  canRecoverWithOption(option: IncidentRecoveryOptionResponse): boolean {
    return Boolean(option.feasible && !this.isRecoveringIncident);
  }

  recoverWithOption(option: IncidentRecoveryOptionResponse): void {
    if (!this.selectedImpactIncident || !this.canRecoverWithOption(option)) {
      return;
    }

    this.isRecoveringIncident = true;
    this.impactAnalysisError = '';
    this.recoverySuccess = '';
    this.changeDetectorRef.detectChanges();

    this.incidentService
      .recoverIncident(this.selectedImpactIncident.id, { option_id: option.option_id })
      .subscribe({
        next: (_response: RecoverIncidentResponse) => {
          this.recoverySuccess = 'incidents.recovery_success';
          this.isRecoveringIncident = false;
          this.closeImpactAnalysis();
          this.loadIncidents();
          this.changeDetectorRef.detectChanges();
        },
        error: (error: HttpErrorResponse) => {
          this.impactAnalysisError = error.error?.detail ?? 'common.error_generic';
          this.isRecoveringIncident = false;
          this.changeDetectorRef.detectChanges();
        },
      });
  }

  incidentTypeKey(type: string): string {
    return `incident.type_${type.toLowerCase()}`;
  }

  tripStatusKey(status: string | null): string {
    return status ? `trips.status.${status.toLowerCase()}` : 'vehicles.not_available';
  }

  vehicleStatusKey(status: string | null): string {
    return status ? `vehicles.status.${status.toLowerCase()}` : 'vehicles.not_available';
  }

  recoveryStrategyKey(strategy: string): string {
    const strategyMap: Record<string, string> = {
      RECOVER_ALL_REMAINING: 'incidents.strategy.recover_all_remaining',
      RECOVER_PICKED_UP_ONLY: 'incidents.strategy.recover_picked_up_only',
      POSTPONE_REMAINING: 'incidents.strategy.postpone_remaining',
    };

    return strategyMap[strategy] ?? strategy;
  }

  routeOrderRefs(option: IncidentRecoveryOptionResponse): string[] {
    const refs = new Set<string>();

    option.route.forEach((stop) => {
      if (!stop.is_virtual && stop.order_ref) {
        refs.add(stop.order_ref);
      }
    });

    return [...refs];
  }

  originalTripOrderRefs(): string[] {
    if (!this.impactAnalysis || this.impactAnalysis.options.length === 0) {
      return [];
    }

    return this.routeOrderRefs(this.impactAnalysis.options[0]);
  }

  formatDate(value: string | null): string {
    if (!value) {
      return '-';
    }

    return new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date(value));
  }

  locationLabel(incident: IncidentListResponse): string {
    if (incident.location_lat === null || incident.location_lon === null) {
      return '-';
    }

    return Number(incident.location_lat).toFixed(5) + ', ' + Number(incident.location_lon).toFixed(5);
  }

  private isStatusFilter(value: string): value is IncidentStatusFilter {
    return ['open', 'resolved', 'all'].includes(value);
  }

  private isTypeFilter(value: string): value is IncidentTypeFilter {
    return ['', 'MINOR', 'MAJOR'].includes(value);
  }
}
