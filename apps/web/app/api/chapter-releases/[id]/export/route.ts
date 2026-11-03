/* Читательская версия главы. Как устроена выдача — в lib/relay.ts.
 *
 * Формат сверяется здесь: что можно попросить у API, решает витрина, а не адресная строка. */

import { NextResponse, type NextRequest } from "next/server";

import { UUID, relayFile } from "../../../../lib/relay";

const FORMATS = new Set(["docx", "markdown", "text"]);

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await params;

  if (!UUID.test(id)) {
    return NextResponse.json({ error: "Версия не найдена" }, { status: 404 });
  }

  const format = request.nextUrl.searchParams.get("format") ?? "docx";

  if (!FORMATS.has(format)) {
    return NextResponse.json({ error: "Неизвестный формат выгрузки" }, { status: 400 });
  }

  return relayFile(`/chapter-releases/${id}/export?${new URLSearchParams({ format })}`);
}
