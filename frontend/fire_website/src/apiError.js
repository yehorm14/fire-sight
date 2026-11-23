// Turns a failed backend response into a message the user can act on.
// A 503 from the API means the model source is unavailable and the backend
// deliberately refused to substitute sample data.
export async function describeFailure(response, fallback) {
  if (response && response.status === 503) {
    let reasons = [];
    try {
      const body = await response.json();
      reasons = body?.detail?.reasons ?? [];
    } catch {
      // body is optional
    }
    const why = reasons.length ? ` (${reasons.join('; ')})` : '';
    return `Model data is unavailable${why}. Switch to sample data or try again later.`;
  }
  return fallback;
}
