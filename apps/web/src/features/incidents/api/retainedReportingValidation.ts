import { matchesApiSchema } from '@/shared/api/generated/assistant';
import type { RetainedReportingPageResponse } from '@/shared/api/generated/assistant';

export function validateRetainedReporting(
  body: unknown,
  captureId: string,
  offset: number,
): RetainedReportingPageResponse {
  if (!matchesApiSchema('RetainedReportingPageResponse', body))
    throw new Error('Received invalid retained source text.');
  const page = body as RetainedReportingPageResponse;
  // API offsets count Unicode code points, not UTF-16 units in JavaScript strings.
  const end = offset + Array.from(page.text).length;
  if (
    page.capture_id !== captureId ||
    page.offset !== offset ||
    end > page.total_characters ||
    Array.from(page.text).length > 4000 ||
    (page.next_offset === null
      ? end !== page.total_characters
      : page.next_offset !== end ||
        page.next_offset <= offset ||
        end >= page.total_characters)
  )
    throw new Error('Received invalid retained source continuation.');
  return page;
}
