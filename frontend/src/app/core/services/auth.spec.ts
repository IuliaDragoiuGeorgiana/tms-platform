import { HttpClient } from '@angular/common/http';

import { AuthService, RoleEnum } from './auth';

describe('AuthService', () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => localStorage.clear());

  it('decodes valid roles and falls back to GUEST for missing or invalid tokens', () => {
    const service = new AuthService({} as HttpClient);

    localStorage.setItem('access_token', makeJwt({ role: RoleEnum.DISPECER }));
    expect(service.getCurrentRole()).toBe(RoleEnum.DISPECER);

    localStorage.setItem('access_token', 'not-a-jwt');
    expect(service.getCurrentRole()).toBe(RoleEnum.GUEST);

    localStorage.removeItem('access_token');
    expect(service.getCurrentRole()).toBe(RoleEnum.GUEST);
  });
});

function makeJwt(payload: object): string {
  const encodedPayload = btoa(JSON.stringify(payload))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');

  return `header.${encodedPayload}.signature`;
}
