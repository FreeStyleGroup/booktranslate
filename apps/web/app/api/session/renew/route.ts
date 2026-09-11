/* Продление сеанса по требованию страницы.

   Обычно доступ продлевает `proxy.ts` — до отрисовки, когда печенья
   доступа уже нет. Сюда страница попадает в другом случае: печенье есть, а
   API токен отверг (доступ закрыт администратором или истёк за секунду до
   клика). Серверный компонент печений ставить не может, а обработчик
   маршрута — может: он обновляет токены и возвращает человека туда, откуда
   тот пришёл, либо стирает сеанс и выводит ко входу.

   Переход сюда из серверного компонента идёт через клиентский
   маршрутизатор Next: ответ обработчика — не дерево компонентов, и
   маршрутизатор докатывает его полной загрузкой страницы, так что новые
   печенья точно доедут до браузера. */

import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";

import { apiFetch, type TokenPair } from "../../../lib/api";
import { RENEWED_COOKIE, clearSession, refreshToken, saveSession } from "../../../lib/session";

const SECURE = process.env.NODE_ENV === "production";

/* Стопор на случай, если API отвергает и свежевыданный токен (расхождение
   ключей, сломанная база сеансов): второе продление за полминуты означает,
   что продлевать бессмысленно, — сеанс стирается, человек видит вход, а не
   «слишком много перенаправлений». */
const RENEWED_TTL = 30;

/** Куда вернуть: только свой относительный путь, чтобы адрес не стал
    открытым перенаправлением на чужой сайт. */
function returnPath(request: NextRequest): string {
  const next = request.nextUrl.searchParams.get("next") ?? "/app";

  return next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\")
    ? next
    : "/app";
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  const jar = await cookies();
  const refresh = await refreshToken();
  const login = NextResponse.redirect(new URL("/login", request.url));

  if (refresh === undefined || jar.get(RENEWED_COOKIE) !== undefined) {
    await clearSession();

    return login;
  }

  let tokens: TokenPair;

  try {
    tokens = await apiFetch<TokenPair>("/auth/refresh", {
      method: "POST",
      body: { refresh_token: refresh },
    });
  } catch {
    // Просрочено, отозвано или API недоступен — в любом случае продлить не
    // вышло, и держать мёртвые печенья незачем.
    await clearSession();

    return login;
  }

  await saveSession(tokens);

  jar.set(RENEWED_COOKIE, "1", {
    httpOnly: true,
    sameSite: "lax",
    secure: SECURE,
    path: "/",
    maxAge: RENEWED_TTL,
  });

  return NextResponse.redirect(new URL(returnPath(request), request.url));
}
