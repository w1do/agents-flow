function resolveApiBase(configuredBase: string | undefined, pageOrigin: string | undefined): string {
  const base = (configuredBase || '').replace(/\/+$/, '');
  if (!base) return '';
  if (!pageOrigin) return base;

  let configuredOrigin: string;
  try {
    configuredOrigin = new URL(base, pageOrigin).origin;
  } catch {
    throw new Error('Invalid VITE_API_BASE. Use a path or a URL with the panel’s same origin.');
  }
  if (configuredOrigin !== pageOrigin) {
    throw new Error('Unsupported VITE_API_BASE origin. The panel and API must use the same origin.');
  }
  return base;
}

export const apiBase = resolveApiBase(
  import.meta.env.VITE_API_BASE,
  typeof window === 'undefined' ? undefined : window.location.origin,
);

let isAuthenticated = false;
export const session = {
  authenticated: () => isAuthenticated,
  save: () => { isAuthenticated = true; },
  clear: () => { isAuthenticated = false; },
};

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

function errorMessage(body: unknown, status: number): string {
  if (status === 401) return 'Сессия истекла или неверные email и пароль.';
  if (status === 403) return 'Недостаточно прав.';
  if (status === 404) return 'Объект не найден.';
  if (status === 409) return 'Данные или статус изменились. Обновите страницу и повторите действие.';
  if (status === 429) return 'Слишком много запросов. Попробуйте позже.';
  if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string') {
    return body.detail;
  }
  return status === 422 ? 'Проверьте заполненные поля.' : `Ошибка API (${status}).`;
}

export async function request<T>(path: string, options: {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT'; body?: unknown; public?: boolean;
} = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  const method = options.method ?? 'GET';
  if (method !== 'GET') {
    headers['X-Requested-With'] = 'XMLHttpRequest';
    if (method !== 'POST' || !path.startsWith('/auth/')) headers['Idempotency-Key'] = crypto.randomUUID();
  }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  let response: Response;
  try {
    response = await fetch(`${apiBase}/api/v1${path}`, {
      method, headers, credentials: 'same-origin',
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  } catch {
    throw new Error('Не удалось связаться с сервером. Проверьте подключение.');
  }
  if (response.status === 401 && !options.public) {
    session.clear();
    if (window.location.pathname !== '/login') window.location.replace('/login');
  }
  let body: unknown = null;
  if (response.status !== 204) {
    try { body = await response.json(); }
    catch {
      if (response.ok) throw new ApiError(response.status, 'Не удалось прочитать ответ сервера.');
    }
  }
  if (!response.ok) throw new ApiError(response.status, errorMessage(body, response.status));
  return body as T;
}

export async function listAll<T>(path: string): Promise<T[]> {
  const result: T[] = [];
  for (let offset = 0; ; offset += 200) {
    const page = await request<T[]>(`${path}${path.includes('?') ? '&' : '?'}offset=${offset}&limit=200`);
    result.push(...page);
    if (page.length < 200) return result;
  }
}

export async function login(email: string, password: string) {
  await request<void>('/auth/login', {
    method: 'POST', body: { email, password }, public: true,
  });
  session.save();
}

export async function restoreSession() {
  await request<void>('/auth/session');
  session.save();
}

export async function logout() {
  try { await request<void>('/auth/logout', { method: 'POST' }); }
  finally { session.clear(); }
}

export const harnessServer = () => apiBase
  ? new URL(apiBase, window.location.origin).href.replace(/\/$/, '') : window.location.origin;
