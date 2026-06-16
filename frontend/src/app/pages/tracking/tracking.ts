import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';

import { TranslatePipe } from '../../core/pipes/translate';
import { OrderService, TrackingResponse } from '../../core/services/order';

@Component({
  selector: 'app-tracking',
  imports: [CommonModule, ReactiveFormsModule, TranslatePipe],
  templateUrl: './tracking.html',
  styleUrl: './tracking.scss',
})
export class Tracking implements OnInit {
  isLoading = false;
  errorMessage = '';
  trackingResult: TrackingResponse | null = null;

  trackingForm;

  constructor(
    private fb: FormBuilder,
    private route: ActivatedRoute,
    private orderService: OrderService,
    private changeDetectorRef: ChangeDetectorRef,
  ) {
    this.trackingForm = this.fb.group({
      token: ['', [Validators.required]],
    });
  }

  ngOnInit(): void {
    const token = this.route.snapshot.paramMap.get('token');

    if (!token) {
      return;
    }

    this.trackingForm.patchValue({ token });
    this.trackOrder();
  }

  trackOrder(): void {
    this.errorMessage = '';
    this.trackingResult = null;

    if (this.trackingForm.invalid) {
      this.trackingForm.markAllAsTouched();
      return;
    }

    const token = this.trackingForm.value.token?.trim() ?? '';
    this.isLoading = true;
    this.changeDetectorRef.detectChanges();

    this.orderService.trackOrder(token).subscribe({
      next: (result) => {
        this.trackingResult = result;
        this.isLoading = false;
        this.changeDetectorRef.detectChanges();
      },
      error: (error: HttpErrorResponse) => {
        this.isLoading = false;
        this.errorMessage = error.error?.detail ?? 'common.error_generic';
        this.changeDetectorRef.detectChanges();
      },
    });
  }

  statusKey(status: string): string {
    return `orders.status.${status.toLowerCase()}`;
  }
}
