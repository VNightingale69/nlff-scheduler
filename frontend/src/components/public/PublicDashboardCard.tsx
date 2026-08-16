import Link from 'next/link';
import type { ComponentType, SVGProps } from 'react';

export type PublicDashboardCardVariant = 'green' | 'blue' | 'orange' | 'purple';

type PublicDashboardCardProps = {
  href: string;
  title: string;
  description: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  variant: PublicDashboardCardVariant;
};

const variantStyles: Record<PublicDashboardCardVariant, { card: string; icon: string; arrow: string }> = {
  green: {
    card: 'border-emerald-200 bg-emerald-50/80 hover:border-emerald-400 hover:bg-emerald-50 focus-visible:ring-emerald-600',
    icon: 'bg-emerald-700 text-white shadow-emerald-900/15',
    arrow: 'text-emerald-800',
  },
  blue: {
    card: 'border-blue-200 bg-blue-50/80 hover:border-blue-400 hover:bg-blue-50 focus-visible:ring-blue-600',
    icon: 'bg-blue-700 text-white shadow-blue-900/15',
    arrow: 'text-blue-800',
  },
  orange: {
    card: 'border-orange-200 bg-orange-50/80 hover:border-orange-400 hover:bg-orange-50 focus-visible:ring-orange-600',
    icon: 'bg-orange-600 text-white shadow-orange-900/15',
    arrow: 'text-orange-800',
  },
  purple: {
    card: 'border-purple-200 bg-purple-50/80 hover:border-purple-400 hover:bg-purple-50 focus-visible:ring-purple-600',
    icon: 'bg-purple-700 text-white shadow-purple-900/15',
    arrow: 'text-purple-800',
  },
};

export default function PublicDashboardCard({ href, title, description, icon: Icon, variant }: PublicDashboardCardProps) {
  const styles = variantStyles[variant];

  return (
    <Link
      href={href}
      aria-label={`${title}: ${description}`}
      className={`group flex min-h-52 cursor-pointer flex-col rounded-3xl border p-5 text-left shadow-sm transition duration-150 hover:-translate-y-0.5 hover:shadow-lg active:translate-y-0 active:scale-[0.99] focus:outline-none focus-visible:ring-4 focus-visible:ring-offset-2 sm:min-h-60 sm:p-6 ${styles.card}`}
    >
      <span aria-hidden='true' className={`flex h-14 w-14 shrink-0 items-center justify-center rounded-full shadow-lg sm:h-16 sm:w-16 ${styles.icon}`}>
        <Icon className='h-7 w-7 sm:h-8 sm:w-8' />
      </span>
      <h2 className='mt-5 text-xl font-extrabold tracking-tight text-slate-950 sm:text-2xl'>{title}</h2>
      <p className='mt-2 text-sm leading-5 text-slate-700 sm:text-base sm:leading-6'>{description}</p>
      <span aria-hidden='true' className={`mt-auto self-end pt-4 text-xl font-bold transition-transform group-hover:translate-x-1 ${styles.arrow}`}>→</span>
    </Link>
  );
}
