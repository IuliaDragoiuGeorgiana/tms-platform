import { ChangeDetectorRef, OnDestroy, Pipe, PipeTransform } from '@angular/core';
import { Subscription } from 'rxjs';

import { I18nService } from '../services/i18n';

@Pipe({
  name: 'translate',
  pure: false,
})
export class TranslatePipe implements PipeTransform, OnDestroy {
  private languageSubscription: Subscription;

  constructor(
    private i18nService: I18nService,
    private changeDetectorRef: ChangeDetectorRef,
  ) {
    this.languageSubscription = this.i18nService.language$.subscribe(() => {
      this.changeDetectorRef.markForCheck();
    });
  }

  transform(key: string): string {
    return this.i18nService.translate(key);
  }

  ngOnDestroy(): void {
    this.languageSubscription.unsubscribe();
  }
}
