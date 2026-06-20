import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';

import { AuthService, RegisterRequest } from '../../core/services/auth';
import { CompanyService, PublicCompanyResponse } from '../../core/services/company';
import { TranslatePipe } from '../../core/pipes/translate';

@Component({
  selector: 'app-signup',
  imports: [CommonModule, ReactiveFormsModule, TranslatePipe],
  templateUrl: './signup.html',
  styleUrl: './signup.scss',
})
export class Signup implements OnInit {
  isLoading = false;
  isLoadingCompanies = false;
  showPassword = false;
  successMessage = '';
  errorMessage = '';
  companyOptionsError = '';
  companies: PublicCompanyResponse[] = [];

  signupForm;

  constructor(
    private fb: FormBuilder,
    private authService: AuthService,
    private companyService: CompanyService,
    private changeDetectorRef: ChangeDetectorRef,
  ) {
    this.signupForm = this.fb.group({
      full_name: ['', [Validators.required, Validators.minLength(3)]],
      email: ['', [Validators.required, Validators.email]],
      phone: [''],
      company_slug: ['', [Validators.required]],
      password: ['', [Validators.required, Validators.minLength(8)]],
    });
  }

  ngOnInit(): void {
    this.loadCompanies();
  }

  togglePasswordVisibility(): void {
    this.showPassword = !this.showPassword;
  }

  loadCompanies(): void {
    this.isLoadingCompanies = true;
    this.companyOptionsError = '';
    this.changeDetectorRef.detectChanges();

    this.companyService.listSignupCompanies().subscribe({
      next: (companies) => {
        this.companies = companies;
        this.isLoadingCompanies = false;
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isLoadingCompanies = false;

        if (error.error?.detail) {
          this.companyOptionsError = error.error.detail;
          this.changeDetectorRef.detectChanges();
          return;
        }

        this.companyOptionsError = 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  onSubmit(): void {
    this.successMessage = '';
    this.errorMessage = '';

    if (this.signupForm.invalid) {
      this.signupForm.markAllAsTouched();
      return;
    }

    const payload = this.signupForm.value as RegisterRequest;

    this.isLoading = true;
    this.changeDetectorRef.detectChanges();

    this.authService.register(payload).subscribe({
      next: () => {
        this.isLoading = false;
        this.successMessage = 'signup.success';
        this.signupForm.reset();
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isLoading = false;

        if (error.error?.detail) {
          this.errorMessage = error.error.detail;
          this.changeDetectorRef.detectChanges();
          return;
        }

        this.errorMessage = 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }
}
