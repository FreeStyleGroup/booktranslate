/* Приём снимка от браузера и пересылка его в API.
 *
 * Тем же способом, что и файл книги (app/api/documents/upload/route.ts): тело не читается, а
 * идёт потоком, и токен добавляется здесь, потому что браузеру он не виден. Запрос с чужой
 * страницы отвергается: печенье с токеном браузер приложил бы и к нему. */

import { NextResponse } from "next/server";

import { API_URL } from "../../../../lib/api";
import { UUID } from "../../../../lib/relay";
import { foreign } from "../../../../lib/same-origin";
import { accessToken, organizationId } from "../../../../lib/session";

// Потолок API — 10 МБ на файл. Запас — на заголовки и границы частей формы.
const MAX_BODY = 11 * 1024 * 1024;

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<NextResponse> {
  if (foreign(request)) {
    return NextResponse.json({ error: "Запрос с чужой страницы" }, { status: 403 });
  }

  const { id } = await params;

  if (!UUID.test(id)) {
    return NextResponse.json({ error: "Замечание не найдено" }, { status: 404 });
  }

  const declared = request.headers.get("content-length");

  if (declared !== null && /^\d+$/.test(declared) && Number(declared) > MAX_BODY) {
    return NextResponse.json({ error: "Файл больше 10 МБ" }, { status: 413 });
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
    // duplex: "half" обязателен для тела-потока и в типах `RequestInit` пока не описан.
    const upstream = await fetch(`${API_URL}/issues/${id}/attachments`, {
      method: "POST",
      headers,
      body: request.body,
      duplex: "half",
    } as RequestInit & { duplex: "half" });

    const answer = (await upstream.json().catch(() => ({}))) as { detail?: unknown };

    if (!upstream.ok) {
      const message = typeof answer.detail === "string" ? answer.detail : "Файл не принят";

      return NextResponse.json({ error: message }, { status: upstream.status });
    }

    return NextResponse.json(answer, { status: upstream.status });
  } catch {
    return NextResponse.json({ error: "Сервис недоступен" }, { status: 502 });
  }
}
