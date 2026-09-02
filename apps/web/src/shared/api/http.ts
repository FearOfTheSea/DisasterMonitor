export async function readJsonResponse<T>(
  response: Response,
  fallbackMessage = `Request failed with status ${response.status}.`,
): Promise<T> {
  let body: unknown;
  try {
    body = await response.json();
  } catch (error) {
    if (!response.ok) {
      throw new Error(fallbackMessage);
    }
    throw error;
  }

  if (!response.ok) {
    throw new Error(responseDetail(body) ?? fallbackMessage);
  }
  return body as T;
}

function responseDetail(body: unknown): string | undefined {
  if (typeof body !== 'object' || body === null || !('detail' in body)) {
    return undefined;
  }
  const detail = body.detail;
  return typeof detail === 'string' && detail ? detail : undefined;
}
