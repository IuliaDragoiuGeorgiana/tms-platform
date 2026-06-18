import { Routes } from '@angular/router';
import { Signup } from './pages/signup/signup';
import { Signin } from './pages/signin/signin';
import { Dashboard } from './pages/dashboard/dashboard';
import { Companies } from './pages/companies/companies';
import { ChangePassword } from './pages/change-password/change-password';
import { Drivers } from './pages/drivers/drivers';
import { Employees } from './pages/employees/employees';
import { Vehicles } from './pages/vehicles/vehicles';
import { Orders } from './pages/orders/orders';
import { Clients } from './pages/clients/clients';
import { Tracking } from './pages/tracking/tracking';
import { Planning } from './pages/planning/planning';
import { Trips } from './pages/trips/trips';
import { superAdminGuard } from './core/guards/super-admin.guard';
import { guestOnlyGuard } from './core/guards/guest-only.guard';
import { authGuard } from './core/guards/auth.guard';
import { managerGuard } from './core/guards/manager.guard';
import { ordersGuard } from './core/guards/orders.guard';
import { clientsGuard } from './core/guards/clients.guard';
import { planningGuard } from './core/guards/planning.guard';
import { tripsGuard } from './core/guards/trips.guard';

export const routes: Routes = [
  {
    path: '',
    redirectTo: 'login',
    pathMatch: 'full',
  },
  {
    path: 'login',
    component: Signin,
    canActivate: [guestOnlyGuard],
  },
  {
    path: 'signup',
    component: Signup,
    canActivate: [guestOnlyGuard],
  },
  {
    path: 'dashboard',
    component: Dashboard,
  },
  {
    path: 'change-password',
    component: ChangePassword,
    canActivate: [authGuard],
  },
  {
    path: 'companies',
    component: Companies,
    canActivate: [superAdminGuard],
  },
  {
    path: 'drivers',
    component: Drivers,
    canActivate: [managerGuard],
  },
  {
    path: 'employees',
    component: Employees,
    canActivate: [managerGuard],
  },
  {
    path: 'vehicles',
    component: Vehicles,
    canActivate: [managerGuard],
  },
  {
    path: 'orders',
    component: Orders,
    canActivate: [ordersGuard],
  },
  {
    path: 'planning',
    component: Planning,
    canActivate: [planningGuard],
  },
  {
    path: 'trips',
    component: Trips,
    canActivate: [tripsGuard],
  },
  {
    path: 'clients',
    component: Clients,
    canActivate: [clientsGuard],
  },
  {
    path: 'tracking',
    component: Tracking,
  },
  {
    path: 'tracking/:token',
    component: Tracking,
  },
];
