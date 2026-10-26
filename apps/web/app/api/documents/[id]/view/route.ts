/* Просмотр PDF в браузере — визуальный эталон рядом с мастером главы.

   Отдельным маршрутом, а не параметром скачивания: здесь файл открывается
   во вкладке, и API отдаёт так только PDF — остальное он отклоняет, потому
   что HTML или SVG заказчика, открытый с домена сервиса, выполнил бы свои
   скрипты от его имени. Как устроена пересылка — в `lib/relay.ts`. */

import { NextResponse } from "next/server";

import { UUID, relayFile } from "../../../../lib/relay";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await params;

  if (!UUID.test(id)) {
    return NextResponse.json({ error: "Документ не найден" }, { status: 404 });
  }

  // Запрет угадывать тип по содержимому уходит к браузеру вместе с файлом:
  // без него PDF с подложенной разметкой мог бы открыться страницей.
  return relayFile(`/documents/${id}/content?view=true`, ["x-content-type-options"]);
}
