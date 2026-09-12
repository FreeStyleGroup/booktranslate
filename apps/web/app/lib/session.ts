/* Сеанс пользователя.

   Токены живут в httpOnly-печеньях, а не в localStorage: любая чужая
   вставка на странице читает localStorage целиком, а httpOnly-печенье
   скрипту не видно вовсе. Проставляет их серверный обработчик
   `app/api/session/route.ts` — браузер токенов не касается.

   Печенья помечены `sameSite: lax` (переход по внешней ссылке не должен
   выглядеть как действие пользователя) и `secure` вне разработки: по HTTP
   `secure`-печенье просто не установится, и локальная разработка сломалась
   бы на ровном месте. */

import { cookies } from "next/headers";

export const ACCESS_COOKIE = "bt_access";
export const REFRESH_COOKIE = "bt_refresh";
export const ORGANIZATION_COOKIE = "bt_org";

/* Отметка «сеанс только что продлён маршрутом /api/session/renew». Нужна
   как стопор: страница, получившая от API отказ при живом печенье, уходит
   на продление, и если API отвергает даже свежевыданный токен, без стопора
   они гоняли бы друг друга по кругу. */
export const RENEWED_COOKIE = "bt_renewed";

const SECURE = process.env.NODE_ENV === "production";

/** Адрес маршрута продления с возвратом на страницу `next`. */
export function renewUrl(next: string): string {
  return `/api/session/renew?next=${encodeURIComponent(next)}`;
}

/** Токен доступа текущего пользователя, если он вошёл. */
export async function accessToken(): Promise<string | undefined> {
  const jar = await cookies();

  return jar.get(ACCESS_COOKIE)?.value;
}

/** Обновление сеанса. Читается только на сервере — в браузер не попадает. */
export async function refreshToken(): Promise<string | undefined> {
  const jar = await cookies();

  return jar.get(REFRESH_COOKIE)?.value;
}

export async function organizationId(): Promise<string | undefined> {
  const jar = await cookies();

  return jar.get(ORGANIZATION_COOKIE)?.value;
}

export async function saveSession(
  tokens: { access_token: string; refresh_token: string; expires_in: number },
  organization?: string,
): Promise<void> {
  const jar = await cookies();

  jar.set(ACCESS_COOKIE, tokens.access_token, {
    httpOnly: true,
    sameSite: "lax",
    secure: SECURE,
    path: "/",
    maxAge: tokens.expires_in,
  });

  // Обновление живёт дольше доступа — на нём и держится сеанс между
  // визитами. Срок задан с запасом относительно срока на стороне API:
  // просроченное обновление отвергнет сам API, и это честнее, чем
  // расходиться с ним на клиенте.
  jar.set(REFRESH_COOKIE, tokens.refresh_token, {
    httpOnly: true,
    sameSite: "lax",
    secure: SECURE,
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });

  if (organization !== undefined) {
    await saveOrganization(organization);
  }
}

/** Запомнить выбранное пространство — например, только что принятое по
 *  приглашению: человек ждёт увидеть его, а не то, где был до этого. */
export async function saveOrganization(organization: string): Promise<void> {
  const jar = await cookies();

  jar.set(ORGANIZATION_COOKIE, organization, {
    httpOnly: true,
    sameSite: "lax",
    secure: SECURE,
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
}

export async function clearSession(): Promise<void> {
  const jar = await cookies();

  for (const name of [ACCESS_COOKIE, REFRESH_COOKIE, ORGANIZATION_COOKIE, RENEWED_COOKIE]) {
    jar.delete(name);
  }
}
