/* Изображение рисунка из книги — оригинал, как он лежал в исходнике.

   Через витрину, а не ссылкой в API: файл лежит за токеном. Политика
   безопасности уходит к браузеру вместе с файлом — SVG из чужой книги,
   открытый по прямой ссылке, без неё выполнил бы свои скрипты с домена
   сервиса. Как устроена пересылка — в `lib/relay.ts`. */

import { NextResponse } from "next/server";

import { UUID, relayFile } from "../../../../../lib/relay";

// Номер изображения в рисунке — небольшое целое: у рисунка их единицы.
const INDEX = /^\d{1,3}$/;

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string; index: string }> },
): Promise<Response> {
  const { id, index } = await params;

  if (!UUID.test(id) || !INDEX.test(index)) {
    return NextResponse.json({ error: "Изображение не найдено" }, { status: 404 });
  }

  return relayFile(`/objects/${id}/images/${index}`, [
    "x-content-type-options",
    "content-security-policy",
    // Файл под ключом не меняется никогда — браузер может держать его в кеше.
    "cache-control",
  ]);
}
