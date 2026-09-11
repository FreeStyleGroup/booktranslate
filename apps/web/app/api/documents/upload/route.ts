/* Приём книги от браузера и пересылка её в API.
 *
 * Отдельным обработчиком, а не серверным действием, по трём причинам, и
 * все три про размер:
 *
 * 1. Серверное действие принимает тело целиком в память и ограничено
 *    мегабайтом по умолчанию. Книга — это десятки мегабайт.
 * 2. Здесь тело не читается вовсе: поток от браузера отдаётся в API как
 *    есть (`duplex: "half"`), и витрина не держит файл в памяти ни на
 *    каком этапе. Разбирать многочастную форму ради того, чтобы собрать
 *    её обратно, — лишняя копия файла в оперативной памяти на каждую
 *    загрузку.
 * 3. Браузер умеет показывать ход отправки только для обычного запроса,
 *    а не для действия. Для файла на тридцать мегабайт полоса — не
 *    украшение: без неё человек не отличает медленную загрузку от
 *    зависшей.
 *
 * Токен добавляется здесь: он лежит в httpOnly-печенье и в браузер не
 * попадает, поэтому обратиться с ним к API может только сервер витрины.
 */

import { NextResponse } from "next/server";

import { API_URL } from "../../../lib/api";
import { foreign } from "../../../lib/same-origin";
import { accessToken, organizationId } from "../../../lib/session";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/* Потолок тела. Согласован с прокси (deploy/Caddyfile) и взят с запасом
   над потолком файла в API (`MAX_UPLOAD_MB`): к самому файлу многочастная
   форма добавляет заголовки и границы частей. Точный предел — за API: он
   его и объявляет, а здесь стоит грубый заслон, чтобы гигабайтное тело не
   поехало через витрину прежде, чем его отвергнут. */
const MAX_BODY = 60 * 1024 * 1024;

export async function POST(request: Request): Promise<NextResponse> {
  if (foreign(request)) {
    return NextResponse.json({ error: "Запрос с чужой страницы" }, { status: 403 });
  }

  const project = new URL(request.url).searchParams.get("project") ?? "";

  if (!UUID.test(project)) {
    return NextResponse.json({ error: "Не указан проект" }, { status: 400 });
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

  const headers: Record<string, string> = {
    "Content-Type": contentType,
    Authorization: `Bearer ${token}`,
  };

  const organization = await organizationId();

  if (organization !== undefined) {
    headers["X-Organization-Id"] = organization;
  }

  // Адрес посетителя: без него API видел бы за всеми пользователями один
  // адрес витрины — и ограничитель частоты считал бы их одним клиентом.
  const forwarded = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim();

  if (forwarded !== undefined && forwarded !== "") {
    headers["X-Forwarded-For"] = forwarded;
  }

  if (request.body === null) {
    return NextResponse.json({ error: "Пустой запрос" }, { status: 400 });
  }

  try {
    // duplex: "half" обязателен для тела-потока и в типах `RequestInit`
    // пока не описан — отсюда расширение типа, а не приведение к any.
    const upstream = await fetch(`${API_URL}/projects/${project}/documents`, {
      method: "POST",
      headers,
      body: request.body,
      duplex: "half",
    } as RequestInit & { duplex: "half" });

    // Ответ API отдаётся как есть: в нём и заведённый документ, и причина
    // отказа — «формат не поддерживается», «файл пуст», «больше лимита».
    // Подменять её общим «не получилось» значит отнять у человека
    // единственную подсказку, что делать дальше.
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
