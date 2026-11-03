/* Выгрузка реестра ошибок. Как это устроено — в lib/relay.ts.
 *
 * Параметры проходят по списку: что можно спросить у API, решает витрина, а не адресная строка.
 * Значения проверяет сам API: их наборы описаны там. */

import { NextResponse, type NextRequest } from "next/server";

import { relayFile } from "../../../lib/relay";

const FORMATS = new Set(["csv", "xlsx"]);
const SINGLE = ["book_id", "chapter_id", "severity", "category", "assignee_id", "query", "archived"];

export async function GET(request: NextRequest): Promise<Response> {
  const wanted = request.nextUrl.searchParams;
  const format = wanted.get("format") ?? "csv";

  if (!FORMATS.has(format)) {
    return NextResponse.json({ error: "Неизвестный формат выгрузки" }, { status: 400 });
  }

  const query = new URLSearchParams({ format });

  for (const name of SINGLE) {
    const value = wanted.get(name);

    if (value !== null) {
      query.set(name, value);
    }
  }

  for (const state of wanted.getAll("state")) {
    query.append("state", state);
  }

  return relayFile(`/issues/export?${query}`, ["x-content-type-options"]);
}
