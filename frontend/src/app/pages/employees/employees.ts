import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';

import { TranslatePipe } from '../../core/pipes/translate';
import { AdminService, InviteUserRequest, UserResponse } from '../../core/services/admin';

interface Employee {
  id: string;
  name: string;
  email: string;
  phone: string;
  roleKey: string;
  statusKey: string;
  isActive: boolean;
}

@Component({
  selector: 'app-employees',
  imports: [CommonModule, ReactiveFormsModule, TranslatePipe],
  templateUrl: './employees.html',
  styleUrl: './employees.scss',
})
export class Employees implements OnInit {
  searchTerm = '';
  showOnlyActive = false;
  isLoadingEmployees = false;
  loadEmployeesError = '';
  isInviteEmployeeOpen = false;
  isInvitingEmployee = false;
  inviteEmployeeSuccess = '';
  inviteEmployeeError = '';
  statusSuccess = '';
  statusError = '';
  employeeToToggle: Employee | null = null;
  isTogglingEmployee = false;

  inviteEmployeeForm;

  constructor(
    private fb: FormBuilder,
    private adminService: AdminService,
    private changeDetectorRef: ChangeDetectorRef,
  ) {
    this.inviteEmployeeForm = this.fb.group({
      full_name: ['', [Validators.required, Validators.minLength(2)]],
      email: ['', [Validators.required, Validators.email]],
      phone: [''],
      role: ['DISPECER', [Validators.required]],
    });
  }

  dispatchers: Employee[] = [];

  drivers: Employee[] = [];

  ngOnInit(): void {
    this.loadEmployees();
  }

  get filteredDispatchers(): Employee[] {
    return this.filterEmployees(this.dispatchers);
  }

  get filteredDrivers(): Employee[] {
    return this.filterEmployees(this.drivers);
  }

  updateSearch(value: string): void {
    this.searchTerm = value;
  }

  updateActiveFilter(value: boolean): void {
    this.showOnlyActive = value;
  }

  loadEmployees(): void {
    this.isLoadingEmployees = true;
    this.loadEmployeesError = '';
    this.changeDetectorRef.detectChanges();

    this.adminService.listEmployees().subscribe({
      next: (employees) => {
        const mappedEmployees = employees.map((employee) => this.mapUserResponse(employee));

        this.dispatchers = mappedEmployees.filter(
          (employee) => employee.roleKey === 'employees.role.dispatcher',
        );
        this.drivers = mappedEmployees.filter(
          (employee) => employee.roleKey === 'employees.role.driver',
        );
        this.isLoadingEmployees = false;
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isLoadingEmployees = false;

        if (error.error?.detail) {
          this.loadEmployeesError = error.error.detail;
          this.changeDetectorRef.detectChanges();
          return;
        }

        this.loadEmployeesError = 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  openInviteEmployee(): void {
    this.isInviteEmployeeOpen = true;
    this.inviteEmployeeSuccess = '';
    this.inviteEmployeeError = '';
    this.statusSuccess = '';
    this.statusError = '';
  }

  closeInviteEmployee(): void {
    this.isInviteEmployeeOpen = false;
    this.inviteEmployeeError = '';
    this.inviteEmployeeForm.reset({
      full_name: '',
      email: '',
      phone: '',
      role: 'DISPECER',
    });
  }

  inviteEmployee(): void {
    this.inviteEmployeeSuccess = '';
    this.inviteEmployeeError = '';

    if (this.inviteEmployeeForm.invalid) {
      this.inviteEmployeeForm.markAllAsTouched();
      return;
    }

    const formValue = this.inviteEmployeeForm.value;
    const payload: InviteUserRequest = {
      email: formValue.email ?? '',
      full_name: formValue.full_name ?? '',
      phone: formValue.phone || null,
      role: formValue.role ?? 'DISPECER',
    };

    this.isInvitingEmployee = true;
    this.changeDetectorRef.detectChanges();

    this.adminService.inviteUser(payload).subscribe({
      next: (response) => {
        this.isInvitingEmployee = false;
        const employee = this.mapInviteResponse(response.user_id, payload);

        if (payload.role === 'SOFER') {
          this.drivers = [employee, ...this.drivers];
        } else {
          this.dispatchers = [employee, ...this.dispatchers];
        }

        this.closeInviteEmployee();
        this.inviteEmployeeSuccess = 'employees.invite_success';
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isInvitingEmployee = false;

        if (error.error?.detail) {
          this.inviteEmployeeError = error.error.detail;
          this.changeDetectorRef.detectChanges();
          return;
        }

        this.inviteEmployeeError = 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  openToggleEmployee(employee: Employee): void {
    this.employeeToToggle = employee;
    this.statusSuccess = '';
    this.statusError = '';
  }

  closeToggleEmployee(): void {
    if (this.isTogglingEmployee) {
      return;
    }

    this.employeeToToggle = null;
  }

  confirmToggleEmployee(): void {
    if (!this.employeeToToggle) {
      return;
    }

    const employee = this.employeeToToggle;
    const request = employee.isActive
      ? this.adminService.deactivateUser(employee.id)
      : this.adminService.activateUser(employee.id);

    this.isTogglingEmployee = true;
    this.statusSuccess = '';
    this.statusError = '';
    this.changeDetectorRef.detectChanges();

    request.subscribe({
      next: (response) => {
        this.isTogglingEmployee = false;
        this.employeeToToggle = null;
        this.statusSuccess = response.is_active
          ? 'employees.status_activated_success'
          : 'employees.status_deactivated_success';
        this.loadEmployees();
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isTogglingEmployee = false;

        if (error.error?.detail) {
          this.statusError = error.error.detail;
          this.changeDetectorRef.detectChanges();
          return;
        }

        this.statusError = 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  private filterEmployees(employees: Employee[]): Employee[] {
    const query = this.searchTerm.trim().toLowerCase();
    const visibleEmployees = this.showOnlyActive
      ? employees.filter((employee) => employee.isActive)
      : employees;

    if (!query) {
      return visibleEmployees;
    }

    return visibleEmployees.filter((employee) =>
      [employee.id, employee.name, employee.email, employee.phone]
        .join(' ')
        .toLowerCase()
        .includes(query),
    );
  }

  private mapInviteResponse(userId: string, payload: InviteUserRequest): Employee {
    return {
      id: userId,
      name: payload.full_name,
      email: payload.email,
      phone: payload.phone || '-',
      roleKey: payload.role === 'SOFER' ? 'employees.role.driver' : 'employees.role.dispatcher',
      statusKey: 'employees.status.active',
      isActive: true,
    };
  }

  private mapUserResponse(user: UserResponse): Employee {
    return {
      id: user.id,
      name: user.full_name,
      email: user.email,
      phone: user.phone || '-',
      roleKey: user.role === 'SOFER' ? 'employees.role.driver' : 'employees.role.dispatcher',
      statusKey: user.is_active ? 'employees.status.active' : 'employees.status.inactive',
      isActive: user.is_active,
    };
  }
}
