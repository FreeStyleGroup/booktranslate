/* Приём файла словаря от браузера и пересылка его в API.
 *
 * Тот же приём, что у загрузки книги (`app/api/documents/upload/route.ts`),
 * и по тем же причинам: тело не читается и не разбирается, а отдаётся в
 * API потоком вместе с полями формы — языковой парой, источником,
 * разрешением на общий словарь. Витрина не держит файл в памяти ни на
 * каком этапе.
 *
 * Токен добавляется здесь: он лежит в httpOnly-печенье и в браузер не
 * попадает, поэтому обратиться с ним к API может только сервер витрины.
 */

import { NextResponse } from "next/server";

import { API_URL } from "../../../lib/api";
import { foreign } from "../../../lib/same-origin";
import { accessToken, organizationId } from "../../../lib/session";

// Согласовано с прокси (deploy/Caddyfile) и потолком файла в API.
const MAX_BODY = 60 * 1024 * 1024;

export async function POST(request: Request): Promise<NextResponse> {
  if (foreign(request)) {
    return NextResponse.json({ error: "Запрос с чужой страницы" }, { status: 403 });
  }

  const declared = request.headers.get("content-length");

  if (declared !== null && /^\d+$/.test(declared) && Number(declared) > MAX_BODY) {
    return NextResponse.json({ error: "Файл больше разрешённого" }, { status: 413 });
  }

  const token = await accessToken();

  if (token === undefined) {
    return NextResponse.json({ error: "Сеанс закончился — войдите заново" }, { status: 401 });
  }

  const contentType = request.headers.get("content-type");

  if (contentType === null || !contentType.includes("multipart/form-data")) {
    return NextResponse.json({ error: "Ожидается файл" }, { status: 400 });
  }

  if (request.body === null) {
    return NextResponse.json({ error: "Пустой запрос" }, { status: 400 });
  }

  const headers: Record<string, string> = {
    "Content-Type": contentType,
    Authorization: `Bearer ${token}`,
  };

  const organization = await organizationId();

  if (organization !== undefined) {
    headers["X-Organization-Id"] = organization;
  }

  const forwarded = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim();

  if (forwarded !== undefined && forwarded !== "") {
    headers["X-Forwarded-For"] = forwarded;
  }

  try {
    const upstream = await fetch(`${API_URL}/glossary/import`, {
      method: "POST",
      headers,
      body: request.body,
      duplex: "half",
    } as RequestInit & { duplex: "half" });

    // Ответ API как есть: в нём и сводка загрузки, и причина отказа —
    // «неизвестный формат», «заведён вручную, не перезаписан».
    return new NextResponse(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    return NextResponse.json(
      { detail: "Сервис недоступен. Попробуйте ещё раз через минуту." },
      { status: 502 },
    );
  }
}
