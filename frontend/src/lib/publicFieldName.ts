const retiredWrapper = /^__retired_generated__[A-Za-z0-9-]+__([\s\S]+)$/;
const adjacentRetiredWrapper = /^retired_generated__[A-Za-z0-9-]+__([\s\S]+)$/;
const internalMarker = /(?:__generated__|__retired_generated__|(?:^|_)retired_(?:$|_))/i;

/** Last-line rendering defense; public APIs remain responsible for canonical data. */
export function publicFieldName(value?: string | null): string | null {
  let label = String(value || '').trim();
  let match = label.match(retiredWrapper);
  if (match) {
    label = match[1];
    while ((match = label.match(retiredWrapper) || label.match(adjacentRetiredWrapper))) label = match[1];
  }
  label = label.trim();
  return label && !internalMarker.test(label) ? label : null;
}
