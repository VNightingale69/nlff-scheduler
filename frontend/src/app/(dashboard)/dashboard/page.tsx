import { APP_NAME, APP_SUBTITLE } from '@/config/branding';

export default function DashboardPage() {
  return <div className='rounded border bg-white p-6'><h1 className='text-2xl font-bold'>{APP_NAME}</h1><p className='mt-1 text-sm font-medium text-slate-700'>{APP_SUBTITLE}</p><p className='mt-3 text-slate-600'>Welcome to the Community Flag Scheduler administrative frontend. Use the sidebar to manage organizations, divisions, host locations, fields, teams, and hosting availability.</p></div>;
}
