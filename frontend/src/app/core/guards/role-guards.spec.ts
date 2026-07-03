import { TestBed } from '@angular/core/testing';
import { ActivatedRouteSnapshot, Router, RouterStateSnapshot } from '@angular/router';

import { ordersGuard } from './orders.guard';
import { planningGuard } from './planning.guard';
import { AuthService, RoleEnum } from '../services/auth';

describe('role guards', () => {
  let currentRole: RoleEnum;
  const router = {
    createUrlTree: vi.fn((commands: string[]) => commands.join('')),
  };

  beforeEach(() => {
    currentRole = RoleEnum.GUEST;
    router.createUrlTree.mockClear();

    TestBed.configureTestingModule({
      providers: [
        {
          provide: AuthService,
          useValue: { getCurrentRole: () => currentRole },
        },
        { provide: Router, useValue: router },
      ],
    });
  });

  it('grants each role only the expected orders and planning access', () => {
    currentRole = RoleEnum.MANAGER;
    expect(runGuard(ordersGuard)).toBe(true);
    expect(runGuard(planningGuard)).toBe(true);

    currentRole = RoleEnum.DISPECER;
    expect(runGuard(ordersGuard)).toBe(true);
    expect(runGuard(planningGuard)).toBe(true);

    currentRole = RoleEnum.CLIENT;
    expect(runGuard(ordersGuard)).toBe(true);
    expect(runGuard(planningGuard)).toBe('/');

    currentRole = RoleEnum.GUEST;
    expect(runGuard(ordersGuard)).toBe('/login');
    expect(runGuard(planningGuard)).toBe('/login');

    currentRole = RoleEnum.SOFER;
    expect(runGuard(ordersGuard)).toBe('/');
    expect(runGuard(planningGuard)).toBe('/');
  });
});

function runGuard(guard: typeof ordersGuard) {
  return TestBed.runInInjectionContext(() =>
    guard({} as ActivatedRouteSnapshot, {} as RouterStateSnapshot),
  );
}
