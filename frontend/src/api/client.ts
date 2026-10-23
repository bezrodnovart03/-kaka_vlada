// HTTP-клиент по правилам docs/API.md §1–3:
// access — только в памяти, refresh — в HttpOnly-cookie (фронт его не видит).
import type { AccessOut, ErrorCode, ErrorOut } from './types';

const BASE = '/api/v1';
const XHR = { 'X-Requested-With': 'XMLHttpRequest' };

let accessToken: string | null = null;
let refreshPromise: Promise<boolean> | null = null;
let onUnauthorized: () => void = () => {};

export class ApiError extends Error {
  readonly status: number;
  readonly code: ErrorCode | 'network_error';
  readonly fields: Record<string, string[]>;

  constructor(status: number, body: Partial<ErrorOut> | null) {
    super(body?.detail ?? (status === 0 ? 'Сервер недоступен' : `Ошибка ${status}`));
    this.status = status;
    this.code = body?.code ?? (status === 0 ? 'network_error' : 'validation_error');
    this.fields = body?.fields ?? {};
  }
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function hasAccessToken(): boolean {
  return accessToken !== null;
}

export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function parse(response: Response): Promise<unknown> {
  if (response.status === 204) return null;
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

async function refreshOnce(): Promise<boolean> {
  const response = await fetch(`${BASE}/auth/refresh`, {
    method: 'POST',
    headers: XHR,
    credentials: 'same-origin',
  });
  if (!response.ok) return false;
  const body = (await response.json()) as AccessOut;
  accessToken = body.access;
  return true;
}

/**
 * Обновляет access по refresh-cookie. Параллельные запросы ждут один общий промис:
 * несколько refresh одновременно нельзя — первый отзовёт токен (ротация).
 * При 401 повторяет один раз через ~300 мс: другая вкладка могла только что обновить cookie.
 */
export function refreshAccess(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      try {
        if (await refreshOnce()) return true;
        await sleep(300);
        return await refreshOnce();
      } catch {
        return false;
      } finally {
        refreshPromise = null;
      }
    })();
  }
  return refreshPromise;
}

type Query = Record<string, string | number | boolean | null | undefined>;

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  body?: unknown;
  query?: Query;
}

function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value));
  }
  const qs = params.toString();
  return `${BASE}${path}${qs ? `?${qs}` : ''}`;
}

export async function request<T>(path: string, options: RequestOptions = {}, retry = true): Promise<T> {
  const headers: Record<string, string> = {};
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;

  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.query), {
      method: options.method ?? 'GET',
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      credentials: 'same-origin',
    });
  } catch {
    throw new ApiError(0, null);
  }

  const body = await parse(response);
  if (response.ok) return body as T;

  const error = new ApiError(response.status, body as ErrorOut | null);
  if (response.status === 401 && error.code === 'unauthorized' && retry) {
    if (await refreshAccess()) return request<T>(path, options, false);
    accessToken = null;
    onUnauthorized();
  }
  throw error;
}

// ── auth: cookie уходит только на /api/v1/auth/* ─────────

export async function login(username: string, password: string): Promise<void> {
  const body = await request<AccessOut>('/auth/login', {
    method: 'POST',
    body: { username, password },
  });
  accessToken = body.access;
}

export async function logout(): Promise<void> {
  try {
    await fetch(`${BASE}/auth/logout`, { method: 'POST', headers: XHR, credentials: 'same-origin' });
  } finally {
    accessToken = null;
  }
}
