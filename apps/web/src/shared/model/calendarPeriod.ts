/** Calendar periods use an inclusive start and an exclusive end. */
export function formatCalendarPeriod(start: string, end: string | null | undefined) {
  const first = new Date(start);
  const upper = end ? new Date(end) : undefined;
  if (
    !upper ||
    !Number.isFinite(first.getTime()) ||
    !Number.isFinite(upper.getTime()) ||
    upper <= first
  )
    return 'Period unresolved';
  const last = new Date(upper.getTime() - 86400000);
  if (
    first.getUTCDate() === 1 &&
    upper.getUTCDate() === 1 &&
    first.getUTCFullYear() * 12 + first.getUTCMonth() + 1 ===
      upper.getUTCFullYear() * 12 + upper.getUTCMonth()
  ) {
    return `${first.toLocaleDateString('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' })} (exact date unresolved)`;
  }
  const lower = first.toISOString().slice(0, 10);
  const final = last.toISOString().slice(0, 10);
  return lower === final
    ? `${lower} (exact time unresolved)`
    : `${lower} to ${final} (exact date unresolved)`;
}
