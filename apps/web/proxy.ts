/* Продление сеанса и охрана кабинета.

   Файл называется `proxy`, а не `middleware`: Next 16 переименовал
   соглашение, старое имя оставлено как устаревшее и ругается при каждой
   сборке. Работает слой в среде Node — для запроса к внутреннему адресу
   API это ничего не меняет.

   Доступ живёт четверть часа, обновление — месяц. Продлевать доступ на
   отрисовке страницы нельзя: серверный компонент не имеет права ставить
   печенья, и попытка это обойти кончается тем, что новый токен получен, но
   не сохранён. Этот слой такое право имеет — он стоит до страницы и
   отвечает вместе с ней.

   Без продления через пятнадцать минут кабинет получал бы отказ на каждый
   запрос к API и подставлял вместо своих чисел демонстрационные: человек
   видит чужие цифры и не понимает, что сеанс кончился. Это хуже честного
   «войдите заново».

   Продлеваем и на переходе по адресу, и на переходе по ссылке внутри
   кабинета: второй приходит не документом, а запросом за деревом
   компонентов, и раньше пропускался — после истечения доступа клик по меню
   рисовал демонстрацию до жёсткой перезагрузки. Не продлеваем только
   предзагрузку ссылок: браузер запускает её пачкой, по всем ссылкам в
   поле зрения, а API меняет токен обновления при каждом использовании и
   считает повторное предъявление кражей — гасит все сеансы. Одновременные
   запросы с одним токеном на всякий случай сводятся к одному обращению к
   API (см. `renew`). */

import { NextResponse, type NextRequest } from "next/server";

const ACCESS_COOKIE = "bt_access";
const REFRESH_COOKIE = "bt_refresh";
const ORGANIZATION_COOKIE = "bt_org";

const API_URL = process.env.API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const SECURE = process.env.NODE_ENV === "production";

const MONTH = 60 * 60 * 24 * 30;

type TokenPair = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
};

/** Предзагрузка ссылки, а не переход по ней. Next помечает её заголовком;
    второй — предзагрузка по сегментам из новой клиентской кеш-схемы. */
function prefetch(request: NextRequest): boolean {
  return (
    request.headers.has("next-router-prefetch") ||
    request.headers.has("next-router-segment-prefetch")
  );
}

export async function proxy(request: NextRequest): Promise<NextResponse> {
  if (request.cookies.get(ACCESS_COOKIE)?.value !== undefined) {
    return NextResponse.next();
  }

  const refresh = request.cookies.get(REFRESH_COOKIE)?.value;
  // Управление доступом показывает свой вход и без сеанса — уводить оттуда
  // на общую страницу входа значит спрятать его от администратора.
  const cabinet = request.nextUrl.pathname.startsWith("/app");

  if (refresh === undefined) {
    return cabinet ? NextResponse.redirect(new URL("/login", request.url)) : NextResponse.next();
  }

  // Предзагрузка без сеанса ничего полезного не соберёт (страницы кабинета
  // динамические, границ загрузки у них нет), а настоящий переход придёт
  // отдельным запросом и продлится ниже.
  if (prefetch(request)) {
    return NextResponse.next();
  }

  const tokens = await renew(refresh, request);

  if (tokens === null) {
    const answer = cabinet
      ? NextResponse.redirect(new URL("/login", request.url))
      : NextResponse.next();

    // Обновление не сработало: оно просрочено, отозвано или сеанс закрыт
    // администратором. Держать его в браузере незачем — следующий запрос
    // повторил бы отказ.
    for (const name of [ACCESS_COOKIE, REFRESH_COOKIE, ORGANIZATION_COOKIE]) {
      answer.cookies.delete(name);
    }

    return answer;
  }

  // Страница отрисуется в этом же проходе и печений ответа ещё не увидит:
  // подменяем печенье и в запросе, иначе она откроется как для гостя.
  request.cookies.set(ACCESS_COOKIE, tokens.access_token);

  const answer = NextResponse.next({ request: { headers: request.headers } });

  answer.cookies.set(ACCESS_COOKIE, tokens.access_token, {
    httpOnly: true,
    sameSite: "lax",
    secure: SECURE,
    path: "/",
    maxAge: tokens.expires_in,
  });

  answer.cookies.set(REFRESH_COOKIE, tokens.refresh_token, {
    httpOnly: true,
    sameSite: "lax",
    secure: SECURE,
    path: "/",
    maxAge: MONTH,
  });

  return answer;
}

/* Обновления, которые идут прямо сейчас, по токену. Два запроса с одним
   токеном (две вкладки, переход и параллельный запрос действия) получают
   один и тот же ответ API вместо двух обращений, второе из которых API
   принял бы за кражу. Карта живёт в процессе: при нескольких экземплярах
   витрины она защищает только внутри каждого, но и там ловит обычный
   случай — параллельные запросы одного браузера. */
const pending = new Map<string, Promise<TokenPair | null>>();

function renew(refresh: string, request: NextRequest): Promise<TokenPair | null> {
  const running = pending.get(refresh);

  if (running !== undefined) {
    return running;
  }

  const attempt = renewOnce(refresh, request).finally(() => {
    pending.delete(refresh);
  });

  pending.set(refresh, attempt);

  return attempt;
}

async function renewOnce(refresh: string, request: NextRequest): Promise<TokenPair | null> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };

  // Адрес посетителя — так же, как в lib/api.ts. Без него API видит за
  // всеми пользователями один адрес витрины, и строгая мера на
  // /auth/refresh срабатывает на всех сразу. Первый адрес ставит наш
  // прокси, чужие значения он отбрасывает.
  const client =
    request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
    request.headers.get("x-real-ip")?.trim();

  if (client) {
    headers["X-Forwarded-For"] = client;
  }

  try {
    const response = await fetch(`${API_URL}/auth/refresh`, {
      method: "POST",
      headers,
      body: JSON.stringify({ refresh_token: refresh }),
      cache: "no-store",
    });

    if (!response.ok) {
      return null;
    }

    return (await response.json()) as TokenPair;
  } catch {
    // API недоступен — это не повод стирать сеанс: страница покажет то, что
    // сможет, а следующий заход попробует снова.
    return null;
  }
}

export const config = {
  matcher: ["/app", "/app/:path*", "/root", "/root/:path*"],
};
