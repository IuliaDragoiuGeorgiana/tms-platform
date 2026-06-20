import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, throwError } from 'rxjs';

import { AuthService } from '../services/auth';

export const authErrorInterceptor: HttpInterceptorFn = (request, next) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  return next(request).pipe(
    catchError((error: unknown) => {
      if (isInvalidTokenError(error) && authService.isLoggedIn()) {
        authService.logout();
        router.navigate(['/login']);
      }

      return throwError(() => error);
    }),
  );
};

function isInvalidTokenError(error: unknown): error is HttpErrorResponse {
  if (!(error instanceof HttpErrorResponse) || error.status !== 401) {
    return false;
  }

  const detail = error.error?.detail;
  return (
    typeof detail === 'string' &&
    (detail === 'Nu s-a putut valida token-ul' ||
      detail.toLowerCase().includes("couldn't validate token"))
  );
}
