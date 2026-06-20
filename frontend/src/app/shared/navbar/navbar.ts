import { ChangeDetectorRef, Component, HostListener, Inject, OnDestroy, inject } from '@angular/core';
import { CommonModule, DOCUMENT } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ReactiveFormsModule, Validators, FormBuilder } from '@angular/forms';
import { Router, RouterLink, RouterLinkActive } from '@angular/router';
import { Observable, Subscription } from 'rxjs';

import { AuthService, RoleEnum, UserResponse } from '../../core/services/auth';
import { I18nService, Language } from '../../core/services/i18n';
import { IncidentReportRequest, IncidentService } from '../../core/services/incident';
import { Theme, ThemeService } from '../../core/services/theme';
import { TripResponse, TripService } from '../../core/services/trip';
import {
  ServiceTimeConfigResponse,
  SystemConfigService,
  UpdateServiceTimeConfigRequest,
} from '../../core/services/system-config';
import { TranslatePipe } from '../../core/pipes/translate';
import { Icon } from '../icon/icon';

interface ServiceTimeRow {
  key: keyof ServiceTimeConfigResponse;
  label: string;
  value: number;
}

interface ServiceTimeGroup {
  title: string;
  rows: ServiceTimeRow[];
}

@Component({
  selector: 'app-navbar',
  imports: [CommonModule, ReactiveFormsModule, RouterLink, RouterLinkActive, TranslatePipe, Icon],
  templateUrl: './navbar.html',
  styleUrl: './navbar.scss',
})
export class Navbar implements OnDestroy {
  readonly RoleEnum = RoleEnum;

  isLoggedIn$: Observable<boolean>;
  currentRole: RoleEnum;
  languages: { code: Language; icon: string; label: string }[];
  currentLanguage: Language;
  currentTheme: Theme;
  currentUser: UserResponse | null = null;
  isOptionsMenuOpen = false;
  isLanguageSubmenuOpen = false;
  isServiceTimeWindowOpen = false;
  isIncidentWindowOpen = false;
  isLoadingServiceTimes = false;
  isSavingServiceTimes = false;
  isLoadingIncidentTrips = false;
  isReportingIncident = false;
  serviceTimeError = '';
  serviceTimeSuccess = '';
  incidentError = '';
  incidentSuccess = '';
  serviceTimeConfig: ServiceTimeConfigResponse | null = null;
  originalServiceTimeConfig: ServiceTimeConfigResponse | null = null;
  serviceTimeGroups: ServiceTimeGroup[] = [];
  incidentTrips: TripResponse[] = [];
  private readonly formBuilder = inject(FormBuilder);
  readonly incidentForm = this.formBuilder.group({
    trip_id: ['', Validators.required],
    type: ['MINOR', Validators.required],
    description: ['', [Validators.required, Validators.maxLength(1000)]],
    location_county: ['', [Validators.required, Validators.maxLength(100)]],
    location_city: ['', [Validators.required, Validators.maxLength(100)]],
    location_street: ['', [Validators.required, Validators.maxLength(200)]],
    location_number: ['', [Validators.required, Validators.maxLength(30)]],
  });
  private languageSubscription: Subscription;
  private themeSubscription: Subscription;
  private roleSubscription: Subscription;
  private loggedInSubscription: Subscription;

  constructor(
    private authService: AuthService,
    private router: Router,
    private i18nService: I18nService,
    private themeService: ThemeService,
    private systemConfigService: SystemConfigService,
    private tripService: TripService,
    private incidentService: IncidentService,
    private changeDetectorRef: ChangeDetectorRef,
    @Inject(DOCUMENT) private document: Document,
  ) {
    this.isLoggedIn$ = this.authService.isLoggedIn$;
    this.currentRole = this.authService.getCurrentRole();
    this.languages = this.i18nService.languages;
    this.currentLanguage = this.i18nService.currentLanguage;
    this.currentTheme = this.themeService.currentTheme;
    this.languageSubscription = this.i18nService.language$.subscribe((language) => {
      this.currentLanguage = language;
      this.changeDetectorRef.detectChanges();
    });
    this.themeSubscription = this.themeService.theme$.subscribe((theme) => {
      this.currentTheme = theme;
      this.changeDetectorRef.detectChanges();
    });
    this.roleSubscription = this.authService.role$.subscribe((role) => {
      this.currentRole = role;
      if (role === RoleEnum.GUEST) {
        this.currentUser = null;
        this.closeServiceTimeWindow();
        this.closeIncidentWindow();
      } else {
        this.loadCurrentUser();
      }
      this.changeDetectorRef.detectChanges();
    });
    this.loggedInSubscription = this.authService.isLoggedIn$.subscribe((isLoggedIn) => {
      if (isLoggedIn) {
        this.loadCurrentUser();
        return;
      }

      this.currentUser = null;
      this.closeServiceTimeWindow();
      this.closeIncidentWindow();
      this.changeDetectorRef.detectChanges();
    });
  }

  setLanguage(language: string): void {
    this.i18nService.setLanguage(language as Language);
    this.isOptionsMenuOpen = false;
    this.isLanguageSubmenuOpen = false;
    this.changeDetectorRef.detectChanges();
  }

  toggleOptionsMenu(): void {
    this.isOptionsMenuOpen = !this.isOptionsMenuOpen;
    if (!this.isOptionsMenuOpen) {
      this.isLanguageSubmenuOpen = false;
    }
    this.changeDetectorRef.detectChanges();
  }

  toggleLanguageSubmenu(): void {
    this.isLanguageSubmenuOpen = !this.isLanguageSubmenuOpen;
    this.changeDetectorRef.detectChanges();
  }

  openChangePassword(): void {
    this.isOptionsMenuOpen = false;
    this.isLanguageSubmenuOpen = false;
    this.changeDetectorRef.detectChanges();
    this.router.navigate(['/change-password']);
  }

  toggleTheme(): void {
    this.themeService.toggleTheme();
    this.isOptionsMenuOpen = false;
    this.isLanguageSubmenuOpen = false;
    this.changeDetectorRef.detectChanges();
  }

  openServiceTimeWindow(): void {
    if (this.currentRole !== RoleEnum.MANAGER) {
      return;
    }

    this.isOptionsMenuOpen = false;
    this.isLanguageSubmenuOpen = false;
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

  openIncidentWindow(): void {
    if (this.currentRole !== RoleEnum.SOFER) {
      return;
    }

    this.isOptionsMenuOpen = false;
    this.isLanguageSubmenuOpen = false;
    this.isIncidentWindowOpen = true;
    this.incidentError = '';
    this.incidentSuccess = '';
    this.incidentTrips = [];
    this.incidentForm.reset({
      trip_id: '',
      type: 'MINOR',
      description: '',
      location_county: '',
      location_city: '',
      location_street: '',
      location_number: '',
    });
    this.loadIncidentTrips();
    this.lockBackgroundScroll();
    this.changeDetectorRef.detectChanges();
  }

  closeIncidentWindow(): void {
    this.isIncidentWindowOpen = false;
    this.isLoadingIncidentTrips = false;
    this.isReportingIncident = false;
    this.incidentError = '';
    this.incidentSuccess = '';
    this.incidentTrips = [];
    this.incidentForm.reset({
      trip_id: '',
      type: 'MINOR',
      description: '',
      location_county: '',
      location_city: '',
      location_street: '',
      location_number: '',
    });
    this.unlockBackgroundScroll();
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

  reportIncident(): void {
    if (this.incidentForm.invalid || this.isReportingIncident) {
      this.incidentForm.markAllAsTouched();
      this.changeDetectorRef.detectChanges();
      return;
    }

    const formValue = this.incidentForm.getRawValue();
    const payload: IncidentReportRequest = {
      trip_id: formValue.trip_id ?? '',
      type: formValue.type === 'MAJOR' ? 'MAJOR' : 'MINOR',
      description: formValue.description?.trim() ?? '',
      location_county: formValue.location_county?.trim() ?? '',
      location_city: formValue.location_city?.trim() ?? '',
      location_street: formValue.location_street?.trim() ?? '',
      location_number: formValue.location_number?.trim() ?? '',
    };

    this.isReportingIncident = true;
    this.incidentError = '';
    this.incidentSuccess = '';
    this.changeDetectorRef.detectChanges();

    this.incidentService.reportIncident(payload).subscribe({
      next: () => {
        this.isReportingIncident = false;
        this.incidentService.notifyTripsRefresh();
        this.closeIncidentWindow();
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.incidentError = error.error?.detail ?? 'common.error_generic';
        this.isReportingIncident = false;
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  get selectedLanguage() {
    return (
      this.languages.find((language) => language.code === this.currentLanguage) ?? this.languages[0]
    );
  }

  get themeIcon(): 'sun' | 'moon' {
    return this.currentTheme === 'dark' ? 'sun' : 'moon';
  }

  logout(): void {
    this.authService.logout();
    this.currentUser = null;
    this.changeDetectorRef.detectChanges();
    this.router.navigate(['/login']);
  }

  @HostListener('document:click')
  closeOptionsMenu(): void {
    this.isOptionsMenuOpen = false;
    this.isLanguageSubmenuOpen = false;
    this.changeDetectorRef.detectChanges();
  }

  ngOnDestroy(): void {
    this.languageSubscription.unsubscribe();
    this.themeSubscription.unsubscribe();
    this.roleSubscription.unsubscribe();
    this.loggedInSubscription.unsubscribe();
    this.unlockBackgroundScroll();
  }

  private loadCurrentUser(): void {
    if (this.currentRole === RoleEnum.GUEST) {
      this.currentUser = null;
      this.changeDetectorRef.detectChanges();
      return;
    }

    this.authService.getMe().subscribe({
      next: (user) => {
        this.currentUser = user;
        this.changeDetectorRef.detectChanges();
      },
      error: (_error: HttpErrorResponse) => {
        this.currentUser = null;
        this.changeDetectorRef.detectChanges();
      },
    });
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

  private loadIncidentTrips(): void {
    this.isLoadingIncidentTrips = true;
    this.incidentError = '';
    this.changeDetectorRef.detectChanges();

    this.tripService.listTrips('IN_PROGRESS').subscribe({
      next: (trips) => {
        this.incidentTrips = trips;
        if (trips.length === 1) {
          this.incidentForm.patchValue({ trip_id: trips[0].id });
        }
        this.isLoadingIncidentTrips = false;
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.incidentError = error.error?.detail ?? 'common.error_generic';
        this.isLoadingIncidentTrips = false;
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
