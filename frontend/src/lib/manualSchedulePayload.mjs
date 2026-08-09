/** Normalize the empty value used by HTML selects before serializing UUIDs. */
export function normalizeOptionalUuid(value) {
  if (typeof value === 'string') {
    const normalized = value.trim();
    return normalized ? normalized : null;
  }
  return value ?? null;
}

/** Optional UUID UI states are equivalent when they all mean "not selected". */
export function optionalUuidChanged(current, original) {
  return normalizeOptionalUuid(current) !== normalizeOptionalUuid(original);
}
