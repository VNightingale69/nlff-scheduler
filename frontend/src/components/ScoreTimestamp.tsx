import { formatDateTimeParts } from '@/lib/displayFormat';

export function ScoreTimestamp({ value }: { value?: string | null }) {
  const parts = formatDateTimeParts(value);

  if (!parts) return <span>—</span>;

  const label = `${parts.dateText} ${parts.timeText}`;
  return (
    <div className='whitespace-nowrap' title={value || undefined} aria-label={label}>
      <div>{parts.dateText}</div>
      <div className='text-xs text-slate-500'>{parts.timeText}</div>
    </div>
  );
}
