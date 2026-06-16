import { ChangeDetectorRef, Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';

import { AuthService, ChangePasswordRequest } from '../../core/services/auth';
import { TranslatePipe } from '../../core/pipes/translate';

@Component({
  selector: 'app-change-password',
  imports: [CommonModule, ReactiveFormsModule, TranslatePipe],
  templateUrl: './change-password.html',
  styleUrl: './change-password.scss',
})
export class ChangePassword {
  isLoading = false;
  errorMessage = '';
  successMessage = '';

  changePasswordForm;

  constructor(
    private fb: FormBuilder,
    private authService: AuthService,
    private router: Router,
    private changeDetectorRef: ChangeDetectorRef,
  ) {
    this.changePasswordForm = this.fb.group({
      current_password: ['', [Validators.required]],
      new_password: ['', [Validators.required, Validators.minLength(8)]],
      confirm_password: ['', [Validators.required]],
    });
  }

  onSubmit(): void {
    this.errorMessage = '';
    this.successMessage = '';

    if (this.changePasswordForm.invalid) {
      this.changePasswordForm.markAllAsTouched();
      return;
    }

    const formValue = this.changePasswordForm.value;

    if (formValue.new_password !== formValue.confirm_password) {
      this.errorMessage = 'change_password.passwords_mismatch';
      return;
    }

    const payload: ChangePasswordRequest = {
      current_password: formValue.current_password ?? '',
      new_password: formValue.new_password ?? '',
    };

    this.isLoading = true;
    this.changeDetectorRef.detectChanges();

    this.authService.changePassword(payload).subscribe({
      next: () => {
        this.isLoading = false;
        this.authService.markPasswordChanged();
        this.successMessage = 'change_password.success';
        this.changeDetectorRef.detectChanges();
        this.router.navigate(['/dashboard']);
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
