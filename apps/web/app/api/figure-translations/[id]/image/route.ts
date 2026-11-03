/* Рисунок с переводом надписей. Как устроена выдача — в lib/relay.ts. */

import { NextResponse, type NextRequest } from "next/server";

import { UUID, relayFile } from "../../../../lib/relay";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await params;

  if (!UUID.test(id)) {
    return NextResponse.json({ error: "Рисунок не найден" }, { status: 404 });
  }

  return relayFile(`/figure-translations/${id}/image`, [
    "cache-control",
    "x-content-type-options",
  ]);
}
