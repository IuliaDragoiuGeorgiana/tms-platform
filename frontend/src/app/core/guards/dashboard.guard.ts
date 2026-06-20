import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AuthService, RoleEnum } from '../services/auth';

export const dashboardGuard: CanActivateFn = () => {
  const authService = inject(AuthService);
  const router = inject(Router);
  const role = authService.getCurrentRole();

  if (role === RoleEnum.SOFER) {
    return router.createUrlTree(['/trips']);
  }

  if (role === RoleEnum.GUEST) {
    return router.createUrlTree(['/login']);
  }

  return true;
};
