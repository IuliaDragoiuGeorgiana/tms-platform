import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import { AuthService, ChangePasswordRequest, ResetPasswordRequest } from '../../core/services/auth';
import { TranslatePipe } from '../../core/pipes/translate';

@Component({
  selector: 'app-change-password',
  imports: [CommonModule, ReactiveFormsModule, TranslatePipe],
  templateUrl: './change-password.html',
  styleUrl: './change-password.scss',
})
export class ChangePassword implements OnInit {
  isLoading = false;
  errorMessage = '';
  successMessage = '';
  resetToken = '';

  changePasswordForm;

  constructor(
    private fb: FormBuilder,
    private authService: AuthService,
    private route: ActivatedRoute,
    private router: Router,
    private changeDetectorRef: ChangeDetectorRef,
  ) {
    this.changePasswordForm = this.fb.group({
      current_password: [''],
      new_password: ['', [Validators.required, Validators.minLength(8)]],
      confirm_password: ['', [Validators.required]],
    });
  }

  ngOnInit(): void {
    this.resetToken =
      this.route.snapshot.queryParamMap.get('token') ?? this.route.snapshot.paramMap.get('token') ?? '';

    const currentPasswordControl = this.changePasswordForm.get('current_password');

    if (this.resetToken) {
      currentPasswordControl?.clearValidators();
    } else {
      currentPasswordControl?.setValidators([Validators.required]);
    }

    currentPasswordControl?.updateValueAndValidity();
  }

  get hasResetToken(): boolean {
    return !!this.resetToken;
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

    this.isLoading = true;
    this.changeDetectorRef.detectChanges();

    if (this.hasResetToken) {
      this.resetPassword(formValue.new_password ?? '');
      return;
    }

    this.changePassword({
      current_password: formValue.current_password ?? '',
      new_password: formValue.new_password ?? '',
    });
  }

  private changePassword(payload: ChangePasswordRequest): void {
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

  private resetPassword(newPassword: string): void {
    const payload: ResetPasswordRequest = {
      token: this.resetToken,
      new_password: newPassword,
    };

    this.authService.resetPassword(payload).subscribe({
      next: () => {
        this.isLoading = false;
        this.successMessage = 'change_password.reset_success';
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
