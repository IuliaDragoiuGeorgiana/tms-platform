import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AuthService, RoleEnum } from '../services/auth';

export const clientsGuard: CanActivateFn = () => {
  const authService = inject(AuthService);
  const router = inject(Router);
  const role = authService.getCurrentRole();

  if ([RoleEnum.SUPER_ADMIN, RoleEnum.MANAGER].includes(role)) {
    return true;
  }

  if (role === RoleEnum.GUEST) {
    return router.createUrlTree(['/login']);
  }

  return router.createUrlTree(['/']);
};
