import { ChangeDetectorRef, Component, HostListener, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Router, RouterLink, RouterLinkActive } from '@angular/router';
import { Observable, Subscription } from 'rxjs';

import { AuthService, RoleEnum, UserResponse } from '../../core/services/auth';
import { I18nService, Language } from '../../core/services/i18n';
import { TranslatePipe } from '../../core/pipes/translate';

@Component({
  selector: 'app-navbar',
  imports: [CommonModule, RouterLink, RouterLinkActive, TranslatePipe],
  templateUrl: './navbar.html',
  styleUrl: './navbar.scss',
})
export class Navbar implements OnDestroy {
  readonly RoleEnum = RoleEnum;

  isLoggedIn$: Observable<boolean>;
  currentRole: RoleEnum;
  languages: { code: Language; icon: string; label: string }[];
  currentLanguage: Language;
  currentUser: UserResponse | null = null;
  isLanguageMenuOpen = false;
  private languageSubscription: Subscription;
  private roleSubscription: Subscription;
  private loggedInSubscription: Subscription;

  constructor(
    private authService: AuthService,
    private router: Router,
    private i18nService: I18nService,
    private changeDetectorRef: ChangeDetectorRef,
  ) {
    this.isLoggedIn$ = this.authService.isLoggedIn$;
    this.currentRole = this.authService.getCurrentRole();
    this.languages = this.i18nService.languages;
    this.currentLanguage = this.i18nService.currentLanguage;
    this.languageSubscription = this.i18nService.language$.subscribe((language) => {
      this.currentLanguage = language;
      this.changeDetectorRef.detectChanges();
    });
    this.roleSubscription = this.authService.role$.subscribe((role) => {
      this.currentRole = role;
      if (role === RoleEnum.GUEST) {
        this.currentUser = null;
      } else {
        this.loadCurrentUser();
      }
      this.changeDetectorRef.detectChanges();
    });
    this.loggedInSubscription = this.authService.isLoggedIn$.subscribe((isLoggedIn) => {
      if (isLoggedIn) {
        this.loadCurrentUser();
        return;
      }

      this.currentUser = null;
      this.changeDetectorRef.detectChanges();
    });
  }

  setLanguage(language: string): void {
    this.i18nService.setLanguage(language as Language);
    this.isLanguageMenuOpen = false;
    this.changeDetectorRef.detectChanges();
  }

  toggleLanguageMenu(): void {
    this.isLanguageMenuOpen = !this.isLanguageMenuOpen;
    this.changeDetectorRef.detectChanges();
  }

  get selectedLanguage() {
    return (
      this.languages.find((language) => language.code === this.currentLanguage) ?? this.languages[0]
    );
  }

  get availableLanguages() {
    return this.languages.filter((language) => language.code !== this.currentLanguage);
  }

  logout(): void {
    this.authService.logout();
    this.currentUser = null;
    this.changeDetectorRef.detectChanges();
    this.router.navigate(['/login']);
  }

  @HostListener('document:click')
  closeLanguageMenu(): void {
    this.isLanguageMenuOpen = false;
    this.changeDetectorRef.detectChanges();
  }

  ngOnDestroy(): void {
    this.languageSubscription.unsubscribe();
    this.roleSubscription.unsubscribe();
    this.loggedInSubscription.unsubscribe();
  }

  private loadCurrentUser(): void {
    if (this.currentRole === RoleEnum.GUEST) {
      this.currentUser = null;
      this.changeDetectorRef.detectChanges();
      return;
    }

    this.authService.getMe().subscribe({
      next: (user) => {
        this.currentUser = user;
        this.changeDetectorRef.detectChanges();
      },
      error: (_error: HttpErrorResponse) => {
        this.currentUser = null;
        this.changeDetectorRef.detectChanges();
      },
    });
  }
}
