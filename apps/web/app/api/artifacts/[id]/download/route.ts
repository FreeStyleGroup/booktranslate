/* Файл выпуска. Как устроена выдача — в lib/relay.ts. Сумма уходит заголовком: файл можно сверить. */

import { NextResponse, type NextRequest } from "next/server";

import { UUID, relayFile } from "../../../../lib/relay";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await params;

  if (!UUID.test(id)) {
    return NextResponse.json({ error: "Файл не найден" }, { status: 404 });
  }

  return relayFile(`/artifacts/${id}/download`, ["x-checksum-sha256"]);
}
