/* Принятие приглашения.

   Через сервер витрины, как и вход: пароль новой учётной записи и токены
   проходят здесь и оседают в httpOnly-печеньях. Два пути, как у API:
   вошедший принимает под своим токеном, гость заводит учётную запись
   паролем из формы — и тут же входит им, потому что токенов принятие не
   выдаёт. */

import { NextResponse } from "next/server";

import { ApiError, apiFetch, type TokenPair } from "../../lib/api";
import { foreign } from "../../lib/same-origin";
import { accessToken, saveOrganization, saveSession } from "../../lib/session";

type Payload = { token?: unknown; password?: unknown; full_name?: unknown };

type Accepted = {
  organization_id: string;
  organization_name: string;
  email: string;
  new_account: boolean;
};

const MAX_BODY = 16 * 1024;

export async function POST(request: Request): Promise<NextResponse> {
  if (foreign(request) || !(request.headers.get("content-type") ?? "").includes("json")) {
    return NextResponse.json({ error: "Запрос с чужой страницы" }, { status: 403 });
  }

  const declared = request.headers.get("content-length");

  if (declared === null || !/^\d+$/.test(declared)) {
    return NextResponse.json({ error: "Не указана длина запроса" }, { status: 411 });
  }

  if (Number(declared) > MAX_BODY) {
    return NextResponse.json({ error: "Слишком большой запрос" }, { status: 413 });
  }

  let payload: Payload;

  try {
    payload = (await request.json()) as Payload;
  } catch {
    return NextResponse.json({ error: "Тело запроса не разобрано" }, { status: 400 });
  }

  const token = text(payload.token);

  if (token === undefined) {
    return NextResponse.json({ error: "В запросе нет ключа приглашения" }, { status: 400 });
  }

  const password = text(payload.password);
  const session = await accessToken();

  try {
    const accepted = await apiFetch<Accepted>("/auth/invitations/accept", {
      method: "POST",
      token: session,
      body: { token, password: password ?? null, full_name: text(payload.full_name) ?? null },
    });

    if (accepted.new_account) {
      // Новая запись входит своим паролем: он только что задан в форме,
      // и второй раз спрашивать его незачем.
      const tokens = await apiFetch<TokenPair>("/auth/login", {
        method: "POST",
        body: { email: accepted.email, password },
      });

      await saveSession(tokens, accepted.organization_id);
    } else {
      // Вошедший остаётся в своём сеансе; меняется только пространство:
      // человек ждёт увидеть то, куда его только что позвали.
      await saveOrganization(accepted.organization_id);
    }

    return NextResponse.json({ ok: true, home: "/app" });
  } catch (error) {
    if (error instanceof ApiError) {
      return NextResponse.json({ error: error.message }, { status: error.status });
    }

    return NextResponse.json(
      { error: "Сервис недоступен. Попробуйте ещё раз через минуту." },
      { status: 502 },
    );
  }
}

function text(value: unknown): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }

  const trimmed = value.trim();

  return trimmed === "" ? undefined : trimmed;
}
