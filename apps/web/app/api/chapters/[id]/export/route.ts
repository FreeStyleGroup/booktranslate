/* Выдача черновой выгрузки. Как это устроено — в lib/relay.ts.
 *
 * Параметры не пробрасываются в API как есть: формат сверяется здесь, а «черновик»
 * переводится в `allow_untranslated`. Что можно попросить у API, решает витрина, а не
 * адресная строка. */

import { NextResponse, type NextRequest } from "next/server";

import { UUID, relayFile } from "../../../../lib/relay";

const FORMATS = new Set(["source", "docx", "markdown", "text"]);

// Сколько блоков ушло исходным текстом: у черновика это обязано дойти до человека.
const UNTRANSLATED_HEADER = "x-untranslated-blocks";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await params;

  if (!UUID.test(id)) {
    return NextResponse.json({ error: "Глава не найдена" }, { status: 404 });
  }

  const wanted = request.nextUrl.searchParams;
  const format = wanted.get("format") ?? "docx";

  if (!FORMATS.has(format)) {
    return NextResponse.json({ error: "Неизвестный формат выгрузки" }, { status: 400 });
  }

  const query = new URLSearchParams({ format });

  if (wanted.get("draft") === "1") {
    query.set("allow_untranslated", "true");
  }

  return relayFile(`/chapters/${id}/export?${query}`, [UNTRANSLATED_HEADER]);
}
