/* Выдача файла из API через витрину.
 *
 * Ссылкой прямо в API нельзя: файл лежит за токеном, а токен живёт в
 * httpOnly-печенье и браузеру не виден. Ссылка на API отдала бы либо
 * отказ, либо — если положить токен в адрес — сам токен в историю
 * браузера, в журнал прокси и в заголовок Referer.
 *
 * Тело переливается потоком: книга на сорок мегабайт, собранная в памяти
 * витрины ради пересылки, — это сорок мегабайт на каждое нажатие.
 *
 * Одно на исходник и на перевод: маршруты отличаются адресом в API и тем,
 * какие заголовки ответа несут смысл для скачивающего.
 */

import { NextResponse } from "next/server";

import { API_URL, clientAddress, readError } from "./api";
import { accessToken, organizationId } from "./session";

export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Заголовки, которые уходят от API как есть: имя и тип файла знает только
// он — под каким именем приносили и в каком формате собрали.
const PASSED = ["content-type", "content-disposition", "content-length"];

/** Переслать файл по адресу API. `extra` — какие ещё заголовки отдать. */
export async function relayFile(path: string, extra: string[] = []): Promise<Response> {
  const token = await accessToken();

  if (token === undefined) {
    return NextResponse.json({ error: "Сеанс закончился — войдите заново" }, { status: 401 });
  }

  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  const organization = await organizationId();

  if (organization !== undefined) {
    headers["X-Organization-Id"] = organization;
  }

  // Адрес посетителя — как и в остальных запросах: иначе ограничитель
  // частоты в API видит за всеми скачивающими одну витрину.
  const client = await clientAddress();

  if (client !== undefined) {
    headers["X-Forwarded-For"] = client;
  }

  let upstream: Response;

  try {
    // Без кеша: перевод меняется с каждой правкой, и вчерашний файл под
    // сегодняшним именем — это подмена, которую заметит заказчик.
    upstream = await fetch(`${API_URL}${path}`, { headers, cache: "no-store" });
  } catch {
    return NextResponse.json({ error: "Сервис недоступен" }, { status: 502 });
  }

  if (!upstream.ok || upstream.body === null) {
    // Причина отказа — от API: «не переведено блоков: 40» человеку нужнее,
    // чем «файл не отдался».
    return NextResponse.json({ error: await readError(upstream) }, { status: upstream.status });
  }

  const passed = new Headers();

  for (const name of [...PASSED, ...extra]) {
    const value = upstream.headers.get(name);

    if (value !== null) {
      passed.set(name, value);
    }
  }

  return new Response(upstream.body, { status: 200, headers: passed });
}
