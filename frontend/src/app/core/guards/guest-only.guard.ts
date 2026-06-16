import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AuthService, RoleEnum } from '../services/auth';

export const guestOnlyGuard: CanActivateFn = () => {
  const authService = inject(AuthService);
  const router = inject(Router);

  if (authService.getCurrentRole() !== RoleEnum.GUEST) {
    return router.createUrlTree(['/dashboard']);
  }

  return true;
};
