/* Выдача исходного файла книги.
 *
 * Через витрину, а не ссылкой прямо в API: файл лежит за токеном, а токен
 * живёт в httpOnly-печенье и браузеру не виден. Ссылка на API отдала бы
 * либо отказ, либо — если положить токен в адрес — сам токен в историю
 * браузера, в журнал прокси и в заголовок Referer.
 *
 * Тело переливается потоком: книга на сорок мегабайт, собранная в памяти
 * витрины ради пересылки, — это сорок мегабайт на каждое нажатие.
 */

import { NextResponse } from "next/server";

import { API_URL } from "../../../../lib/api";
import { accessToken, organizationId } from "../../../../lib/session";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await params;

  if (!UUID.test(id)) {
    return NextResponse.json({ error: "Документ не найден" }, { status: 404 });
  }

  const token = await accessToken();

  if (token === undefined) {
    return NextResponse.json({ error: "Сеанс закончился — войдите заново" }, { status: 401 });
  }

  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  const organization = await organizationId();

  if (organization !== undefined) {
    headers["X-Organization-Id"] = organization;
  }

  let upstream: Response;

  try {
    upstream = await fetch(`${API_URL}/documents/${id}/content`, { headers });
  } catch {
    return NextResponse.json({ error: "Сервис недоступен" }, { status: 502 });
  }

  if (!upstream.ok || upstream.body === null) {
    return NextResponse.json({ error: "Файл не отдался" }, { status: upstream.status });
  }

  // Имя файла и тип приходят от API: он один знает, под каким именем файл
  // приносили и в каком он формате.
  const passed = new Headers();

  for (const name of ["content-type", "content-disposition", "content-length"]) {
    const value = upstream.headers.get(name);

    if (value !== null) {
      passed.set(name, value);
    }
  }

  return new Response(upstream.body, { status: 200, headers: passed });
}
