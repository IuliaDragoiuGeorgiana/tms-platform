import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';

import { TranslatePipe } from '../../core/pipes/translate';
import { AdminService, InviteUserRequest } from '../../core/services/admin';
import {
  CompanyResponse,
  CompanyStatsResponse,
  CompanyService,
  CreateCompanyRequest,
  UpdateCompanyRequest,
} from '../../core/services/company';

interface Company {
  id: string;
  name: string;
  slug: string;
  plan: string;
  vatId?: string;
  depotCounty?: string;
  depotCity?: string;
  depotStreet?: string;
  depotNumber?: string;
  depotLatitude?: number | null;
  depotLongitude?: number | null;
  depotLocation?: string;
  isActive: boolean;
  statusKey: string;
  managers: number;
  dispatchers: number;
  drivers: number;
  clients: number;
  vehicles: number;
  maxUsers: number;
  maxVehicles: number;
  ordersThisMonth: number;
}

@Component({
  selector: 'app-companies',
  imports: [CommonModule, ReactiveFormsModule, TranslatePipe],
  templateUrl: './companies.html',
  styleUrl: './companies.scss',
})
export class Companies implements OnInit {
  searchTerm = '';
  isAddCompanyOpen = false;
  isViewCompanyOpen = false;
  isEditCompanyOpen = false;
  isInviteManagerOpen = false;
  isCreatingCompany = false;
  isUpdatingCompany = false;
  isInvitingManager = false;
  isLoadingCompanies = false;
  isLoadingCompanyStats = false;
  togglingCompanyIds = new Set<string>();
  createCompanySuccess = '';
  createCompanyError = '';
  updateCompanyError = '';
  inviteManagerSuccess = '';
  inviteManagerError = '';
  loadCompaniesError = '';
  loadCompanyStatsError = '';
  companyActionError = '';
  companyActionSuccess = '';
  selectedViewCompany: Company | null = null;
  selectedCompanyStats: CompanyStatsResponse | null = null;
  selectedEditCompany: Company | null = null;
  selectedInviteCompany: Company | null = null;

  companyForm;
  editCompanyForm;
  inviteManagerForm;

  constructor(
    private fb: FormBuilder,
    private companyService: CompanyService,
    private adminService: AdminService,
    private changeDetectorRef: ChangeDetectorRef,
  ) {
    this.companyForm = this.fb.group({
      name: ['', [Validators.required, Validators.minLength(2)]],
      slug: ['', [Validators.required, Validators.pattern(/^[a-zA-Z0-9_-]+$/)]],
      plan: ['FREE', [Validators.required]],
      max_vehicles: [10, [Validators.required, Validators.min(1)]],
      max_users: [20, [Validators.required, Validators.min(1)]],
      depot_county: [''],
      depot_city: [''],
      depot_street: [''],
      depot_number: [''],
    });

    this.editCompanyForm = this.fb.group({
      name: ['', [Validators.required, Validators.minLength(2)]],
      plan: ['FREE', [Validators.required]],
      is_active: [true],
      max_vehicles: [10, [Validators.required, Validators.min(1)]],
      max_users: [20, [Validators.required, Validators.min(1)]],
      depot_county: [''],
      depot_city: [''],
      depot_street: [''],
      depot_number: [''],
    });

    this.inviteManagerForm = this.fb.group({
      full_name: ['', [Validators.required, Validators.minLength(2)]],
      email: ['', [Validators.required, Validators.email]],
      phone: [''],
    });
  }

  companies: Company[] = [];

  ngOnInit(): void {
    this.loadCompanies();
  }

  get filteredCompanies(): Company[] {
    const query = this.searchTerm.trim().toLowerCase();

    if (!query) {
      return this.companies;
    }

    return this.companies.filter((company) =>
      [
        company.id,
        company.name,
        company.slug,
        company.plan,
        company.vatId ?? '',
        company.depotCounty ?? '',
        company.depotCity ?? '',
        company.depotStreet ?? '',
        company.depotNumber ?? '',
        company.depotLocation ?? '',
        company.statusKey,
        String(company.managers),
        String(company.dispatchers),
        String(company.drivers),
        String(company.clients),
        String(company.vehicles),
        String(company.ordersThisMonth),
      ]
        .join(' ')
        .toLowerCase()
        .includes(query),
    );
  }

  updateSearch(value: string): void {
    this.searchTerm = value;
  }

  loadCompanies(): void {
    this.isLoadingCompanies = true;
    this.loadCompaniesError = '';
    this.companyActionError = '';
    this.companyActionSuccess = '';
    this.inviteManagerError = '';
    this.inviteManagerSuccess = '';
    this.updateCompanyError = '';

    this.companyService.listCompanies().subscribe({
      next: (companies) => {
        this.isLoadingCompanies = false;
        this.companies = companies.map((company) => this.mapCompanyResponse(company));
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isLoadingCompanies = false;

        if (error.error?.detail) {
          this.loadCompaniesError = error.error.detail;
          this.changeDetectorRef.detectChanges();
          return;
        }

        this.loadCompaniesError = 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  openAddCompany(): void {
    this.isAddCompanyOpen = true;
    this.createCompanySuccess = '';
    this.createCompanyError = '';
    this.companyActionError = '';
    this.companyActionSuccess = '';
    this.inviteManagerError = '';
    this.inviteManagerSuccess = '';
    this.updateCompanyError = '';
  }

  closeAddCompany(): void {
    this.isAddCompanyOpen = false;
    this.createCompanySuccess = '';
    this.createCompanyError = '';
    this.companyForm.reset({
      name: '',
      slug: '',
      plan: 'FREE',
      max_vehicles: 10,
      max_users: 20,
      depot_county: '',
      depot_city: '',
      depot_street: '',
      depot_number: '',
    });
  }

  openViewCompany(company: Company): void {
    this.selectedViewCompany = company;
    this.selectedCompanyStats = null;
    this.isViewCompanyOpen = true;
    this.companyActionError = '';
    this.loadCompanyStatsError = '';
    this.loadCompanyStats(company.id);
  }

  closeViewCompany(): void {
    this.isViewCompanyOpen = false;
    this.selectedViewCompany = null;
    this.selectedCompanyStats = null;
    this.loadCompanyStatsError = '';
    this.isLoadingCompanyStats = false;
  }

  loadCompanyStats(companyId: string): void {
    this.isLoadingCompanyStats = true;

    this.companyService.getCompanyStats(companyId).subscribe({
      next: (stats) => {
        this.isLoadingCompanyStats = false;
        this.selectedCompanyStats = stats;
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isLoadingCompanyStats = false;

        if (error.error?.detail) {
          this.loadCompanyStatsError = error.error.detail;
          this.changeDetectorRef.detectChanges();
          return;
        }

        this.loadCompanyStatsError = 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  openEditCompany(company: Company): void {
    this.selectedEditCompany = company;
    this.isEditCompanyOpen = true;
    this.updateCompanyError = '';
    this.createCompanySuccess = '';
    this.companyActionError = '';
    this.companyActionSuccess = '';
    this.inviteManagerError = '';
    this.inviteManagerSuccess = '';
    this.editCompanyForm.reset({
      name: company.name,
      plan: company.plan,
      is_active: company.isActive,
      max_vehicles: company.maxVehicles,
      max_users: company.maxUsers,
      depot_county: company.depotCounty ?? '',
      depot_city: company.depotCity ?? '',
      depot_street: company.depotStreet ?? '',
      depot_number: company.depotNumber ?? '',
    });
  }

  closeEditCompany(): void {
    this.isEditCompanyOpen = false;
    this.selectedEditCompany = null;
    this.updateCompanyError = '';
    this.editCompanyForm.reset({
      name: '',
      plan: 'FREE',
      is_active: true,
      max_vehicles: 10,
      max_users: 20,
      depot_county: '',
      depot_city: '',
      depot_street: '',
      depot_number: '',
    });
  }

  openInviteManager(company: Company): void {
    this.selectedInviteCompany = company;
    this.isInviteManagerOpen = true;
    this.inviteManagerError = '';
    this.inviteManagerSuccess = '';
    this.createCompanySuccess = '';
    this.companyActionError = '';
    this.companyActionSuccess = '';
  }

  closeInviteManager(): void {
    this.isInviteManagerOpen = false;
    this.selectedInviteCompany = null;
    this.inviteManagerError = '';
    this.inviteManagerForm.reset({
      full_name: '',
      email: '',
      phone: '',
    });
  }

  createCompany(): void {
    this.createCompanySuccess = '';
    this.createCompanyError = '';
    this.companyActionError = '';
    this.companyActionSuccess = '';

    if (this.companyForm.invalid) {
      this.companyForm.markAllAsTouched();
      return;
    }

    const formValue = this.companyForm.value;
    const payload: CreateCompanyRequest = {
      name: formValue.name ?? '',
      slug: formValue.slug ?? '',
      plan: formValue.plan ?? 'FREE',
      max_vehicles: formValue.max_vehicles ?? 10,
      max_users: formValue.max_users ?? 20,
      depot_county: this.emptyToNull(formValue.depot_county),
      depot_city: this.emptyToNull(formValue.depot_city),
      depot_street: this.emptyToNull(formValue.depot_street),
      depot_number: this.emptyToNull(formValue.depot_number),
    };

    this.isCreatingCompany = true;

    this.companyService.createCompany(payload).subscribe({
      next: (company) => {
        this.isCreatingCompany = false;
        this.companies = [this.mapCompanyResponse(company), ...this.companies];
        this.closeAddCompany();
        this.createCompanySuccess = 'companies.create_success';
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isCreatingCompany = false;

        if (error.error?.detail) {
          this.createCompanyError = error.error.detail;
          this.changeDetectorRef.detectChanges();
          return;
        }

        this.createCompanyError = 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  updateCompany(): void {
    this.updateCompanyError = '';
    this.companyActionSuccess = '';

    if (!this.selectedEditCompany) {
      this.updateCompanyError = 'common.error_generic';
      return;
    }

    if (this.editCompanyForm.invalid) {
      this.editCompanyForm.markAllAsTouched();
      return;
    }

    const formValue = this.editCompanyForm.value;
    const payload: UpdateCompanyRequest = {
      name: formValue.name ?? '',
      plan: formValue.plan ?? 'FREE',
      is_active: Boolean(formValue.is_active),
      max_vehicles: formValue.max_vehicles ?? 10,
      max_users: formValue.max_users ?? 20,
      depot_county: this.emptyToNull(formValue.depot_county),
      depot_city: this.emptyToNull(formValue.depot_city),
      depot_street: this.emptyToNull(formValue.depot_street),
      depot_number: this.emptyToNull(formValue.depot_number),
    };

    this.isUpdatingCompany = true;

    this.companyService.updateCompany(this.selectedEditCompany.id, payload).subscribe({
      next: (company) => {
        this.isUpdatingCompany = false;
        this.companies = this.companies.map((currentCompany) =>
          currentCompany.id === company.id ? this.mapCompanyResponse(company) : currentCompany,
        );
        this.companyActionSuccess = 'companies.update_success';
        this.closeEditCompany();
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isUpdatingCompany = false;

        if (error.error?.detail) {
          this.updateCompanyError = error.error.detail;
          this.changeDetectorRef.detectChanges();
          return;
        }

        this.updateCompanyError = 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  toggleCompanyStatus(company: Company): void {
    this.companyActionError = '';
    this.companyActionSuccess = '';
    this.createCompanySuccess = '';
    this.togglingCompanyIds.add(company.id);

    const request$ = company.isActive
      ? this.companyService.deactivateCompany(company.id)
      : this.companyService.activateCompany(company.id);

    request$.subscribe({
      next: (updatedCompany) => {
        this.togglingCompanyIds.delete(company.id);
        this.companies = this.companies.map((currentCompany) =>
          currentCompany.id === updatedCompany.id
            ? this.mapCompanyResponse(updatedCompany)
            : currentCompany,
        );
        this.companyActionSuccess = updatedCompany.is_active
          ? 'companies.status_activated_success'
          : 'companies.status_deactivated_success';
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.togglingCompanyIds.delete(company.id);

        if (error.error?.detail) {
          this.companyActionError = error.error.detail;
          this.changeDetectorRef.detectChanges();
          return;
        }

        this.companyActionError = 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  inviteManager(): void {
    this.inviteManagerError = '';
    this.inviteManagerSuccess = '';

    if (!this.selectedInviteCompany) {
      this.inviteManagerError = 'common.error_generic';
      return;
    }

    if (this.inviteManagerForm.invalid) {
      this.inviteManagerForm.markAllAsTouched();
      return;
    }

    const formValue = this.inviteManagerForm.value;
    const payload: InviteUserRequest = {
      email: formValue.email ?? '',
      full_name: formValue.full_name ?? '',
      phone: formValue.phone || null,
      role: 'MANAGER',
      company_id: this.selectedInviteCompany.id,
    };

    this.isInvitingManager = true;

    this.adminService.inviteUser(payload).subscribe({
      next: () => {
        this.isInvitingManager = false;
        this.inviteManagerSuccess = 'companies.invite_manager_success';
        this.closeInviteManager();
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isInvitingManager = false;

        if (error.error?.detail) {
          this.inviteManagerError = error.error.detail;
          this.changeDetectorRef.detectChanges();
          return;
        }

        this.inviteManagerError = 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  isTogglingCompany(companyId: string): boolean {
    return this.togglingCompanyIds.has(companyId);
  }

  private mapCompanyResponse(company: CompanyResponse): Company {
    return {
      id: company.id,
      name: company.name,
      slug: company.slug,
      plan: company.plan,
      depotCounty: company.depot_county ?? undefined,
      depotCity: company.depot_city ?? undefined,
      depotStreet: company.depot_street ?? undefined,
      depotNumber: company.depot_number ?? undefined,
      depotLatitude: company.depot_lat,
      depotLongitude: company.depot_lon,
      depotLocation: this.formatDepotLocation(company),
      isActive: company.is_active,
      statusKey: company.is_active ? 'companies.status.active' : 'companies.status.disabled',
      managers: company.managers_count ?? 0,
      dispatchers: company.dispatchers_count ?? 0,
      drivers: company.drivers_count ?? 0,
      clients: company.clients_count ?? 0,
      vehicles: company.vehicles_count ?? 0,
      maxUsers: company.max_users ?? 0,
      maxVehicles: company.max_vehicles ?? 0,
      ordersThisMonth: 0,
    };
  }

  private emptyToNull(value: string | null | undefined): string | null {
    const trimmedValue = value?.trim();
    return trimmedValue ? trimmedValue : null;
  }

  private formatDepotLocation(company: CompanyResponse): string {
    return [
      company.depot_street,
      company.depot_number,
      company.depot_city,
      company.depot_county,
    ]
      .map((value) => value?.trim())
      .filter(Boolean)
      .join(', ');
  }
}
