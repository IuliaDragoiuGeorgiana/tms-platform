import { DOCUMENT } from '@angular/common';
import { Inject, Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';

export type Theme = 'light' | 'dark';

@Injectable({
  providedIn: 'root',
})
export class ThemeService {
  private readonly storageKey = 'theme';
  private readonly themeSubject = new BehaviorSubject<Theme>(this.getInitialTheme());

  readonly theme$ = this.themeSubject.asObservable();

  constructor(@Inject(DOCUMENT) private document: Document) {
    this.applyTheme(this.themeSubject.value);
  }

  get currentTheme(): Theme {
    return this.themeSubject.value;
  }

  toggleTheme(): void {
    this.setTheme(this.currentTheme === 'dark' ? 'light' : 'dark');
  }

  setTheme(theme: Theme): void {
    localStorage.setItem(this.storageKey, theme);
    this.themeSubject.next(theme);
    this.applyTheme(theme);
  }

  private applyTheme(theme: Theme): void {
    this.document.body.dataset['theme'] = theme;
  }

  private getInitialTheme(): Theme {
    const storedTheme = localStorage.getItem(this.storageKey);

    if (storedTheme === 'light' || storedTheme === 'dark') {
      return storedTheme;
    }

    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
}
