/* Выдача исходного файла книги. Как это устроено — в `lib/relay.ts`. */

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

  return relayFile(`/documents/${id}/content`);
}
