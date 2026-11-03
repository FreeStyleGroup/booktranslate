/* Вложение замечания. Как это устроено — в lib/relay.ts.
 *
 * Тип определён в API по байтам: показываются только растровые, остальное уходит скачиванием, и
 * `nosniff` не даёт браузеру угадывать другой. Политика содержимого здесь общая для сайта
 * (next.config.ts): она заменяет заголовок API, поэтому пересылать его незачем. */

import { NextResponse } from "next/server";

import { UUID, relayFile } from "../../../../../lib/relay";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string; attachmentId: string }> },
): Promise<Response> {
  const { id, attachmentId } = await params;

  if (!UUID.test(id) || !UUID.test(attachmentId)) {
    return NextResponse.json({ error: "Вложение не найдено" }, { status: 404 });
  }

  return relayFile(`/issues/${id}/attachments/${attachmentId}`, ["x-content-type-options"]);
}
