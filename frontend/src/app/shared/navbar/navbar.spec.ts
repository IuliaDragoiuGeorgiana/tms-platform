import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { EMPTY } from 'rxjs';

import { AuthService, RoleEnum } from '../../core/services/auth';
import { I18nService } from '../../core/services/i18n';
import { IncidentService } from '../../core/services/incident';
import { SystemConfigService } from '../../core/services/system-config';
import { ThemeService } from '../../core/services/theme';
import { TripService } from '../../core/services/trip';
import { Navbar } from './navbar';

describe('Navbar', () => {
  let component: Navbar;
  let fixture: ComponentFixture<Navbar>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [Navbar],
      providers: [
        provideRouter([]),
        {
          provide: AuthService,
          useValue: {
            isLoggedIn$: EMPTY,
            role$: EMPTY,
            getCurrentRole: () => RoleEnum.GUEST,
          },
        },
        {
          provide: I18nService,
          useValue: {
            languages: [],
            currentLanguage: 'ro',
            language$: EMPTY,
            translate: (key: string) => key,
          },
        },
        {
          provide: ThemeService,
          useValue: {
            currentTheme: 'light',
            theme$: EMPTY,
          },
        },
        { provide: SystemConfigService, useValue: {} },
        { provide: TripService, useValue: {} },
        { provide: IncidentService, useValue: {} },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(Navbar);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
