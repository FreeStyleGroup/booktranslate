import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { load, type FoundBlock } from "../../lib/work";
import { KIND_ONE } from "../labels";
import "../work.css";
import "../books/books.css";

export const metadata: Metadata = {
  title: "Блок по коду — BookTranslate",
  description: "Переход к блоку книги по его постоянному коду.",
};

/* Переход к блоку по коду.

   Код вида `CH03-B0042` находит блок в книге, `BK01-CH03-B0042` — где
   угодно в пространстве: в какой бы главе и на какой странице списка он
   ни стоял. Найденный блок открывается на своей странице главы и
   подсвечивается.

   Блок, выведенный из действия, в текущей версии мастера места не имеет —
   но и «не найдено» он не стал: на него ссылаются прежние версии. Тогда
   здесь показывается он сам. */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const CODE = /^(?:BK\d+-)?CH\d+-B\d+$/i;

// Тот же размер страницы, что на экране главы: по нему считается, на
// какой странице стоит блок.
const PER_PAGE = 50;

export default async function FindPage({
  searchParams,
}: {
  searchParams: Promise<{ code?: string; book?: string }>;
}) {
  const { code: raw, book } = await searchParams;
  const code = (raw ?? "").trim().toUpperCase();
  const inBook = book !== undefined && UUID.test(book) ? book : undefined;

  if (!CODE.test(code)) {
    return (
      <Answer>
        Код блока выглядит так: <b>CH03-B0042</b> в пределах книги или <b>BK01-CH03-B0042</b>{" "}
        где угодно.
      </Answer>
    );
  }

  const here = `/app/find?code=${encodeURIComponent(code)}`;
  const found = await load<FoundBlock>(
    inBook !== undefined
      ? `/books/${inBook}/blocks/${encodeURIComponent(code)}`
      : `/blocks/lookup?code=${encodeURIComponent(code)}`,
    here,
  );

  if (found.error !== undefined) {
    return <Answer>{found.error}</Answer>;
  }

  const { block, position } = found.data;
  const chapter = `/app/books/${found.data.book_id}/chapters/${found.data.chapter_id}`;

  if (position !== null) {
    const offset = Math.floor(position / PER_PAGE) * PER_PAGE;
    redirect(`${chapter}${offset > 0 ? `?offset=${offset}` : ""}#${block.code}`);
  }

  return (
    <section className="tile">
      <div className="tile__head">
        <h2>{block.full_code}</h2>
        <span className="chip chip--warn">выведен из действия</span>
      </div>
      <p className="tile__note">
        {KIND_ONE[block.kind] ?? block.kind}. Этого блока нет в текущей версии мастера: текст
        главы с тех пор изменился, и блок заменён другим. На него по-прежнему ссылаются прежние
        версии.
      </p>
      <p className="bk-block-text">{block.source_text}</p>
      <div className="tile__foot">
        <Link className="btn btn--ghost btn--small" href={chapter}>
          К главе
        </Link>
      </div>
    </section>
  );
}

function Answer({ children }: { children: ReactNode }) {
  return (
    <section className="tile">
      <h2>Блок по коду</h2>
      <p className="tile__empty">{children}</p>
    </section>
  );
}
