import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AuthService, RoleEnum } from '../services/auth';

export const analyticsGuard: CanActivateFn = () => {
  const authService = inject(AuthService);
  const router = inject(Router);

  const currentRole = authService.getCurrentRole();
  if (currentRole === RoleEnum.MANAGER || currentRole === RoleEnum.DISPECER) {
    return true;
  }

  return router.createUrlTree(['/']);
};
