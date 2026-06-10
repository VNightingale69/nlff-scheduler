import { API_URL } from '@/lib/api';

type Props = {
  src?: string | null;
  name?: string | null;
  size?: number;
  className?: string;
};

export function logoSource(src?: string | null) {
  if (!src) return null;
  if (/^https?:\/\//i.test(src)) return src;
  const apiBase = API_URL.replace(/\/api$/, '');
  return `${apiBase}${src.startsWith('/') ? src : `/${src}`}`;
}

function initials(value?: string | null) {
  const words = String(value || 'Community').trim().split(/\s+/).filter(Boolean);
  return (words[0]?.[0] || 'C') + (words[1]?.[0] || '');
}

export default function CommunityLogo({ src, name, size = 24, className = '' }: Props) {
  const dimension = `${size}px`;
  const resolvedSrc = logoSource(src);
  if (resolvedSrc) {
    return <img src={resolvedSrc} alt={`${name || 'Community'} logo`} className={`shrink-0 rounded bg-white object-contain ring-1 ring-slate-200 ${className}`} style={{ width: dimension, height: dimension }} />;
  }
  return <span aria-label={`${name || 'Community'} logo fallback`} className={`inline-flex shrink-0 items-center justify-center rounded bg-slate-100 text-[10px] font-bold uppercase text-slate-600 ring-1 ring-slate-200 ${className}`} style={{ width: dimension, height: dimension }}>{initials(name)}</span>;
}
