/* Обращения к API.

   Адрес берётся из окружения: витрина и API разъехались намеренно и живут на
   разных доменах. На сервере доступен внутренний адрес (`API_URL`), в
   браузере — публичный (`NEXT_PUBLIC_API_URL`); в разработке оба сводятся к
   локальному запуску. */

import { headers } from "next/headers";

export const API_URL =
  process.env.API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/* Адрес посетителя, если запрос пришёл от него.

   Витрина ходит в API сама, и без этого заголовка API видел бы за всеми
   пользователями один адрес — адрес витрины: ограничитель частоты считал
   бы их одним клиентом, а список сессий показывал бы одну строку на всех.
   Первый адрес в X-Forwarded-For ставит наш же прокси перед витриной и
   чужие значения отбрасывает, поэтому ему можно верить. Вне запроса —
   сборка, консоль — адреса нет, и это не ошибка. */
async function clientAddress(): Promise<string | undefined> {
  try {
    const incoming = await headers();
    const forwarded = incoming.get("x-forwarded-for")?.split(",")[0]?.trim();

    return forwarded || incoming.get("x-real-ip")?.trim() || undefined;
  } catch {
    return undefined;
  }
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** API не признал токен: просрочен, отозван или учётная запись закрыта. */
export function unauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

type Options = {
  method?: string;
  body?: unknown;
  token?: string;
  organizationId?: string;
};

/** Запрос к API с разбором ошибки в человеческое сообщение. */
export async function apiFetch<T>(path: string, options: Options = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };

  if (options.token !== undefined) {
    headers.Authorization = `Bearer ${options.token}`;
  }

  if (options.organizationId !== undefined) {
    headers["X-Organization-Id"] = options.organizationId;
  }

  const client = await clientAddress();

  if (client !== undefined) {
    headers["X-Forwarded-For"] = client;
  }

  const response = await fetch(`${API_URL}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    // Данные кабинета зависят от того, кто пришёл: закешированный ответ
    // показал бы одному пользователю страницу другого.
    cache: "no-store",
  });

  if (!response.ok) {
    throw new ApiError(response.status, await readError(response));
  }

  // Пустой ответ — тоже ответ: отзыв сеанса возвращает 204, и попытка
  // разобрать пустое тело как JSON сорвала бы удавшийся запрос.
  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

/** Сообщение об ошибке из ответа API — или из его отсутствия. */
async function readError(response: Response): Promise<string> {
  try {
    const payload: unknown = await response.json();

    if (typeof payload === "object" && payload !== null && "detail" in payload) {
      const detail = (payload as { detail: unknown }).detail;

      if (typeof detail === "string") {
        return detail;
      }

      // Ошибка разбора схемы приходит списком: показываем первую — остальные
      // обычно про то же самое поле.
      if (Array.isArray(detail) && detail.length > 0) {
        const first: unknown = detail[0];

        if (typeof first === "object" && first !== null && "msg" in first) {
          return String((first as { msg: unknown }).msg);
        }
      }
    }
  } catch {
    // Ответ без JSON — например от прокси. Ниже вернётся общий текст.
  }

  return `Сервер ответил ошибкой ${response.status}`;
}

export type TokenPair = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
};

export type Membership = {
  organization_id: string;
  organization_name: string;
  role: string;
};

export type CurrentUser = {
  user: {
    id: string;
    email: string;
    full_name: string | null;
    status: "pending" | "active" | "suspended";
    // Администратор площадки — не роль в организации: он распоряжается
    // доступом, а не работой в чужом рабочем пространстве.
    is_superuser: boolean;
  };
  memberships: Membership[];
};
