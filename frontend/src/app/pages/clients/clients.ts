import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';

import { TranslatePipe } from '../../core/pipes/translate';
import { AdminService, UserResponse } from '../../core/services/admin';
import { AuthService, RoleEnum } from '../../core/services/auth';

interface ClientCompanyGroup {
  companyId: string;
  companyName: string;
  clients: UserResponse[];
}

interface CompanyFilterOption {
  companyId: string;
  companyName: string;
}

@Component({
  selector: 'app-clients',
  imports: [CommonModule, TranslatePipe],
  templateUrl: './clients.html',
  styleUrl: './clients.scss',
})
export class Clients implements OnInit {
  readonly RoleEnum = RoleEnum;
  readonly currentRole: RoleEnum;

  clients: UserResponse[] = [];
  collapsedCompanyIds = new Set<string>();
  approvingClientIds = new Set<string>();
  searchTerm = '';
  selectedCompanyId = 'all';
  isLoadingClients = false;
  loadClientsError = '';

  constructor(
    private adminService: AdminService,
    private authService: AuthService,
    private changeDetectorRef: ChangeDetectorRef,
  ) {
    this.currentRole = this.authService.getCurrentRole();
  }

  ngOnInit(): void {
    this.loadClients();
  }

  get filteredClients(): UserResponse[] {
    const query = this.searchTerm.trim().toLowerCase();
    const clients =
      this.currentRole === RoleEnum.SUPER_ADMIN && this.selectedCompanyId !== 'all'
        ? this.clients.filter((client) => (client.company_id ?? 'no-company') === this.selectedCompanyId)
        : this.clients;

    if (!query) {
      return clients;
    }

    return clients.filter((client) =>
      [client.id, client.company_id ?? '', client.company_name ?? '', client.full_name, client.email, client.phone ?? '']
        .join(' ')
        .toLowerCase()
        .includes(query),
    );
  }

  get groupedClients(): ClientCompanyGroup[] {
    const groups = new Map<string, ClientCompanyGroup>();

    for (const client of this.filteredClients) {
      const companyId = client.company_id ?? 'no-company';
      const companyName = client.company_name ?? client.company_id ?? '';
      const existingGroup = groups.get(companyId);

      if (existingGroup) {
        existingGroup.clients.push(client);
        continue;
      }

      groups.set(companyId, {
        companyId,
        companyName,
        clients: [client],
      });
    }

    return Array.from(groups.values()).sort((firstGroup, secondGroup) =>
      this.getCompanyGroupName(firstGroup).localeCompare(this.getCompanyGroupName(secondGroup)),
    );
  }

  get companyFilterOptions(): CompanyFilterOption[] {
    const options = new Map<string, CompanyFilterOption>();

    for (const client of this.clients) {
      const companyId = client.company_id ?? 'no-company';

      if (!options.has(companyId)) {
        options.set(companyId, {
          companyId,
          companyName: client.company_name ?? client.company_id ?? '',
        });
      }
    }

    return Array.from(options.values()).sort((firstOption, secondOption) =>
      this.getCompanyOptionName(firstOption).localeCompare(this.getCompanyOptionName(secondOption)),
    );
  }

  loadClients(): void {
    this.isLoadingClients = true;
    this.loadClientsError = '';
    this.changeDetectorRef.detectChanges();

    this.adminService.listClients().subscribe({
      next: (clients) => {
        this.clients = clients;
        this.pruneCollapsedCompanyIds(clients);
        this.pruneSelectedCompanyId(clients);
        this.isLoadingClients = false;
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isLoadingClients = false;

        if (error.error?.detail) {
          this.loadClientsError = error.error.detail;
          this.changeDetectorRef.detectChanges();
          return;
        }

        this.loadClientsError = 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  updateSearch(value: string): void {
    this.searchTerm = value;
  }

  updateSelectedCompany(companyId: string): void {
    this.selectedCompanyId = companyId;
    this.changeDetectorRef.detectChanges();
  }

  approveClient(client: UserResponse): void {
    this.approvingClientIds.add(client.id);
    this.loadClientsError = '';
    this.changeDetectorRef.detectChanges();

    this.adminService.approveUser(client.id).subscribe({
      next: (updatedClient) => {
        this.clients = this.clients.map((existingClient) =>
          existingClient.id === updatedClient.id ? updatedClient : existingClient,
        );
        this.approvingClientIds.delete(client.id);
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.approvingClientIds.delete(client.id);
        this.loadClientsError = error.error?.detail ?? 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  isApprovingClient(clientId: string): boolean {
    return this.approvingClientIds.has(clientId);
  }

  isCompanyCollapsed(companyId: string): boolean {
    return this.collapsedCompanyIds.has(companyId);
  }

  toggleCompanyGroup(companyId: string): void {
    if (this.collapsedCompanyIds.has(companyId)) {
      this.collapsedCompanyIds.delete(companyId);
    } else {
      this.collapsedCompanyIds.add(companyId);
    }

    this.changeDetectorRef.detectChanges();
  }

  getCompanyGroupName(group: ClientCompanyGroup): string {
    return group.companyName || 'clients.no_company';
  }

  getCompanyOptionName(option: CompanyFilterOption): string {
    return option.companyName || 'clients.no_company';
  }

  approvalStatusKey(client: UserResponse): string {
    return client.is_approved ? 'clients.status.approved' : 'clients.status.pending';
  }

  activityStatusKey(client: UserResponse): string {
    return client.is_active ? 'clients.status.active' : 'clients.status.inactive';
  }

  private pruneCollapsedCompanyIds(clients: UserResponse[]): void {
    const companyIds = new Set(clients.map((client) => client.company_id ?? 'no-company'));
    this.collapsedCompanyIds = new Set(
      Array.from(this.collapsedCompanyIds).filter((companyId) => companyIds.has(companyId)),
    );
  }

  private pruneSelectedCompanyId(clients: UserResponse[]): void {
    if (this.selectedCompanyId === 'all') {
      return;
    }

    const companyIds = new Set(clients.map((client) => client.company_id ?? 'no-company'));

    if (!companyIds.has(this.selectedCompanyId)) {
      this.selectedCompanyId = 'all';
    }
  }
}
