/* Продление сеанса и охрана кабинета.

   Доступ живёт четверть часа, обновление — месяц. Продлевать доступ на
   отрисовке страницы нельзя: серверный компонент не имеет права ставить
   печенья, и попытка это обойти кончается тем, что новый токен получен, но
   не сохранён. Промежуточный слой такое право имеет — он стоит до страницы
   и отвечает вместе с ней.

   Без продления через пятнадцать минут кабинет получал бы отказ на каждый
   запрос к API и подставлял вместо своих чисел демонстрационные: человек
   видит чужие цифры и не понимает, что сеанс кончился. Это хуже честного
   «войдите заново».

   Продление делается только на переходе по адресу, а не на каждом запросе
   страницы. API меняет токен обновления при каждом использовании и считает
   повторное предъявление кражей — гасит все сеансы. Два параллельных
   запроса со старым токеном выглядели бы ровно так, поэтому обновляемся
   один раз за переход. */

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

export async function middleware(request: NextRequest): Promise<NextResponse> {
  if (request.cookies.get(ACCESS_COOKIE)?.value !== undefined) {
    return NextResponse.next();
  }

  const refresh = request.cookies.get(REFRESH_COOKIE)?.value;
  // Управление доступом показывает свой вход и без сеанса — уводить оттуда
  // на общую страницу входа значит спрятать его от администратора.
  const cabinet = request.nextUrl.pathname.startsWith("/app");
  const navigation = (request.headers.get("sec-fetch-dest") ?? "document") === "document";

  if (refresh === undefined || !navigation) {
    return cabinet && refresh === undefined
      ? NextResponse.redirect(new URL("/login", request.url))
      : NextResponse.next();
  }

  const tokens = await renew(refresh);

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

async function renew(refresh: string): Promise<TokenPair | null> {
  try {
    const response = await fetch(`${API_URL}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
