import { ChangeDetectorRef, Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { AuthService, ForgotPasswordRequest } from '../../core/services/auth';
import { TranslatePipe } from '../../core/pipes/translate';

@Component({
  selector: 'app-forgot-password',
  imports: [CommonModule, ReactiveFormsModule, RouterLink, TranslatePipe],
  templateUrl: './forgot-password.html',
  styleUrl: './forgot-password.scss',
})
export class ForgotPassword {
  isLoading = false;
  errorMessage = '';
  successMessage = '';

  forgotPasswordForm;

  constructor(
    private fb: FormBuilder,
    private authService: AuthService,
    private changeDetectorRef: ChangeDetectorRef,
  ) {
    this.forgotPasswordForm = this.fb.group({
      email: ['', [Validators.required, Validators.email]],
    });
  }

  onSubmit(): void {
    this.errorMessage = '';
    this.successMessage = '';

    if (this.forgotPasswordForm.invalid) {
      this.forgotPasswordForm.markAllAsTouched();
      return;
    }

    const payload = this.forgotPasswordForm.value as ForgotPasswordRequest;

    this.isLoading = true;
    this.changeDetectorRef.detectChanges();

    this.authService.forgotPassword(payload).subscribe({
      next: () => {
        this.isLoading = false;
        this.successMessage = 'forgot_password.success';
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
