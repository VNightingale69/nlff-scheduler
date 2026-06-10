'use client';

import { useEffect, useState } from 'react';
import { API_URL } from '@/lib/api';

type Props = {
  src?: string | null;
  logoUrl?: string | null;
  name?: string | null;
  communityName?: string | null;
  teamName?: string | null;
  altText?: string | null;
  size?: number;
  className?: string;
};

export function logoSource(src?: string | null) {
  if (!src) return null;
  if (/^https?:\/\//i.test(src)) return src;
  const apiBase = API_URL.replace(/\/api$/, '');
  return `${apiBase}${src.startsWith('/') ? src : `/${src}`}`;
}

export function communityInitials(value?: string | null) {
  const words = String(value || 'Community').trim().split(/\s+/).filter(Boolean);
  return (words[0]?.[0] || 'C') + (words[1]?.[0] || '');
}

export default function CommunityLogo({ src, logoUrl, name, communityName, teamName, altText, size = 24, className = '' }: Props) {
  const fallbackName = communityName || name || teamName || 'Community';
  const sourceValue = logoUrl ?? src;
  const resolvedSrc = logoSource(sourceValue);
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const dimension = `${size}px`;
  const showImage = Boolean(resolvedSrc && failedSrc !== resolvedSrc);

  useEffect(() => {
    setFailedSrc(null);
  }, [resolvedSrc]);

  if (showImage && resolvedSrc) {
    return (
      <img
        src={resolvedSrc}
        alt={altText || `${fallbackName} logo`}
        className={`shrink-0 rounded bg-white object-contain ring-1 ring-slate-200 ${className}`}
        style={{ width: dimension, height: dimension }}
        onError={() => setFailedSrc(resolvedSrc)}
        data-community-logo='image'
      />
    );
  }

  return (
    <span
      aria-label={`${fallbackName} logo fallback`}
      className={`inline-flex shrink-0 items-center justify-center rounded bg-slate-100 text-[10px] font-bold uppercase text-slate-600 ring-1 ring-slate-200 ${className}`}
      style={{ width: dimension, height: dimension }}
      data-community-logo='fallback'
    >
      {communityInitials(fallbackName)}
    </span>
  );
}
