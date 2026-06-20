import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AuthService, RoleEnum } from '../services/auth';

export const authGuard: CanActivateFn = (route) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  if (route.queryParamMap.get('token') || route.paramMap.get('token')) {
    return true;
  }

  if (authService.getCurrentRole() === RoleEnum.GUEST) {
    return router.createUrlTree(['/login']);
  }

  return true;
};
