export const formatDisplayDate = (value: string | null | undefined) => {
  if (!value) return '-';

  const raw = String(value);
  const datePart = raw.split('T')[0];
  const match = datePart.match(/^(\d{4})-(\d{2})-(\d{2})$/);

  if (match) {
    const [, year, month, day] = match;
    return `${month}/${day}/${year}`;
  }

  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return raw;

  return new Intl.DateTimeFormat('en-US', {
    month: '2-digit',
    day: '2-digit',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(parsed);
};

export const formatDisplayTime = (value: string | null | undefined) => {
  if (!value) return '-';

  const raw = String(value).trim();
  const match = raw.match(/^(\d{1,2}):(\d{2})(?::\d{2}(?:\.\d+)?)?$/);

  if (!match) return raw;

  const hour = Number(match[1]);
  const minute = Number(match[2]);

  if (Number.isNaN(hour) || Number.isNaN(minute) || hour < 0 || hour > 23 || minute < 0 || minute > 59) {
    return raw;
  }

  const period = hour >= 12 ? 'PM' : 'AM';
  const displayHour = hour % 12 || 12;

  return `${String(displayHour).padStart(2, '0')}:${String(minute).padStart(2, '0')} ${period}`;
};

export const formatDisplayDateTime = (date: string | null | undefined, time: string | null | undefined) => {
  const displayDate = formatDisplayDate(date);
  const displayTime = formatDisplayTime(time);

  if (displayDate === '-' && displayTime === '-') return '-';
  if (displayDate === '-') return displayTime;
  if (displayTime === '-') return displayDate;
  return `${displayDate} ${displayTime}`;
};

export const LEAGUE_TIME_ZONE = process.env.NEXT_PUBLIC_LEAGUE_TIME_ZONE || 'America/Chicago';

export type DisplayDateTimeParts = {
  dateText: string;
  timeText: string;
};

/** Formats an API timestamp in the league timezone without changing its stored value. */
export const formatDateTimeParts = (value: string | null | undefined): DisplayDateTimeParts | null => {
  if (!value) return null;

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;

  return {
    dateText: new Intl.DateTimeFormat('en-US', {
      timeZone: LEAGUE_TIME_ZONE,
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    }).format(parsed),
    timeText: new Intl.DateTimeFormat('en-US', {
      timeZone: LEAGUE_TIME_ZONE,
      hour: 'numeric',
      minute: '2-digit',
    }).format(parsed),
  };
};

export const formatDateTime = (value: string | null | undefined) => {
  const parts = formatDateTimeParts(value);
  return parts ? `${parts.dateText} ${parts.timeText}` : '—';
};

export const formatDisplayTimestamp = (value: string | null | undefined) => {
  return formatDateTime(value);
};
