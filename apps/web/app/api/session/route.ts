/* Вход, регистрация и выход.

   Обработчик стоит между браузером и API намеренно: пароль и токены
   проходят через сервер витрины и оседают в httpOnly-печеньях, недоступных
   скриптам страницы. Отдавать токен в браузер и хранить его в localStorage
   значило бы отдать сеанс любой чужой вставке на странице. */

import { NextResponse } from "next/server";

import { ApiError, apiFetch, type CurrentUser, type TokenPair } from "../../lib/api";
import { clearSession, refreshToken, saveSession } from "../../lib/session";

type Payload = {
  mode?: unknown;
  email?: unknown;
  password?: unknown;
  full_name?: unknown;
  organization_name?: unknown;
};

/* Обработчик маршрута — не серверное действие, и встроенной защиты от
   запроса с чужой страницы у него нет. Без проверки источника чужой сайт
   отправляет сюда форму и получает в браузере жертвы сеанс, открытый под
   учётной записью нападающего: дальше жертва загружает свою книгу в чужое
   рабочее пространство. `SameSite` от этого не спасает — она ограничивает
   отправку уже имеющихся печений, а не установку новых.

   Проверяются оба признака: заголовок источника и тип содержимого. Форма
   со страницы не может отправить `application/json`, а запрос без источника
   к делу отношения не имеет — обе двери закрываются одной проверкой. */
function foreign(request: Request): boolean {
  const origin = request.headers.get("origin");
  const host = request.headers.get("host");

  if (origin === null || host === null) {
    return true;
  }

  try {
    return new URL(origin).host !== host;
  } catch {
    return true;
  }
}

export async function POST(request: Request): Promise<NextResponse> {
  if (foreign(request) || !(request.headers.get("content-type") ?? "").includes("json")) {
    return NextResponse.json({ error: "Запрос с чужой страницы" }, { status: 403 });
  }

  const payload = (await request.json()) as Payload;

  const email = text(payload.email);
  const password = text(payload.password);

  if (email === undefined || password === undefined) {
    return NextResponse.json({ error: "Нужны почта и пароль" }, { status: 400 });
  }

  const register = payload.mode === "register";

  if (register && text(payload.organization_name) === undefined) {
    return NextResponse.json(
      { error: "Нужно название рабочего пространства" },
      { status: 400 },
    );
  }

  try {
    // Регистрация — заявка: сеанса она не открывает, потому что доступ
    // открывает администратор. Форме отвечаем этим же словом.
    if (register) {
      await apiFetch<{ status: string }>("/auth/register", {
        method: "POST",
        body: {
          email,
          password,
          full_name: text(payload.full_name) ?? null,
          organization_name: text(payload.organization_name),
        },
      });

      return NextResponse.json({ ok: true, pending: true });
    }

    const tokens = await apiFetch<TokenPair>("/auth/login", {
      method: "POST",
      body: { email, password },
    });

    // Организация запоминается сразу: человек работает в нескольких, и без
    // выбранной каждый запрос к API требовал бы её заголовком.
    const me = await apiFetch<CurrentUser>("/auth/me", { token: tokens.access_token });

    await saveSession(tokens, me.memberships[0]?.organization_id);

    return NextResponse.json({ ok: true });
  } catch (error) {
    if (error instanceof ApiError) {
      return NextResponse.json({ error: error.message }, { status: error.status });
    }

    // Сеть, а не отказ: API не поднят или недоступен. Показывать «неверный
    // пароль» в этом случае — врать пользователю.
    return NextResponse.json(
      { error: "Сервис недоступен. Попробуйте ещё раз через минуту." },
      { status: 502 },
    );
  }
}

export async function DELETE(request: Request): Promise<NextResponse> {
  if (foreign(request)) {
    return NextResponse.json({ error: "Запрос с чужой страницы" }, { status: 403 });
  }

  const refresh = await refreshToken();

  // Печенья стереть мало: обновление живёт в базе API месяц и после
  // «выхода» продолжает открывать сеансы. Выход — это отзыв на стороне
  // API, а очистка браузера лишь его следствие.
  if (refresh !== undefined) {
    try {
      await apiFetch("/auth/logout", { method: "POST", body: { refresh_token: refresh } });
    } catch {
      // Недоступный API не повод оставить человека внутри: печенья стираем
      // в любом случае, отзыв догонит при следующей попытке обновиться.
    }
  }

  await clearSession();

  return NextResponse.json({ ok: true });
}

function text(value: unknown): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }

  const trimmed = value.trim();

  return trimmed === "" ? undefined : trimmed;
}
