import { ChangeDetectorRef, Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { Router, RouterLink } from '@angular/router';

import { AuthService, LoginRequest } from '../../core/services/auth';
import { TranslatePipe } from '../../core/pipes/translate';

@Component({
  selector: 'app-signin',
  imports: [CommonModule, ReactiveFormsModule, RouterLink, TranslatePipe],
  templateUrl: './signin.html',
  styleUrl: './signin.scss',
})
export class Signin {
  isLoading = false;
  errorMessage = '';

  signinForm;

  constructor(
    private fb: FormBuilder,
    private authService: AuthService,
    private router: Router,
    private changeDetectorRef: ChangeDetectorRef,
  ) {
    this.signinForm = this.fb.group({
      email: ['', [Validators.required, Validators.email]],
      password: ['', [Validators.required]],
    });
  }

  onSubmit(): void {
    this.errorMessage = '';

    if (this.signinForm.invalid) {
      this.signinForm.markAllAsTouched();
      return;
    }

    const payload = this.signinForm.value as LoginRequest;

    this.isLoading = true;
    this.changeDetectorRef.detectChanges();

    this.authService.login(payload).subscribe({
      next: (token) => {
        this.isLoading = false;
        this.authService.saveSession(token);
        this.changeDetectorRef.detectChanges();

        if (token.must_change_password) {
          this.router.navigate(['/change-password']);
          return;
        }

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
