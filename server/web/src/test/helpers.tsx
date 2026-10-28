import { afterEach, beforeEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';
import { session } from '../api/client';

export const fetchMock = vi.fn();
export const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

beforeEach(() => { session.clear(); vi.stubGlobal('fetch', fetchMock); fetchMock.mockReset(); });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });
