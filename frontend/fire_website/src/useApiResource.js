import { useEffect, useState } from 'react';
import { describeFailure } from './apiError';
import { BACKEND_URL } from './config';

export function useApiResource(path, failureMessage) {
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState(null);

  useEffect(() => {
    const controller = new AbortController();

    async function fetchResource() {
      try {
        const response = await fetch(BACKEND_URL + path, { signal: controller.signal });
        if (!response.ok) throw new Error(await describeFailure(response, failureMessage));
        const data = await response.json();
        if (!controller.signal.aborted) setResult({ path, attempt, status: 'ready', data });
      } catch (error) {
        if (!controller.signal.aborted) {
          setResult({ path, attempt, status: 'error', error: error instanceof TypeError ? failureMessage : error.message });
        }
      }
    }

    fetchResource();
    return () => controller.abort();
  }, [path, attempt, failureMessage]);

  return {
    ...(result?.path === path && result.attempt === attempt ? result : { status: 'loading' }),
    retry: () => setAttempt((current) => current + 1),
  };
}
