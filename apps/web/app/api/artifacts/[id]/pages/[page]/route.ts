/* Страница PDF картинкой для аудита. Номер сверяется здесь: в адрес API идёт только число. */

import { NextResponse, type NextRequest } from "next/server";

import { UUID, relayFile } from "../../../../../lib/relay";

const PAGE = /^[1-9][0-9]{0,4}$/;

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string; page: string }> },
): Promise<Response> {
  const { id, page } = await params;

  if (!UUID.test(id) || !PAGE.test(page)) {
    return NextResponse.json({ error: "Страница не найдена" }, { status: 404 });
  }

  return relayFile(`/artifacts/${id}/pages/${page}/image`, ["cache-control"]);
}
