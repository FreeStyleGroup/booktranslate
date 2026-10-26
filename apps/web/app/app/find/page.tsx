import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { load, type FoundBlock, type FoundObject } from "../../lib/work";
import { KIND_ONE } from "../labels";
import "../work.css";
import "../books/books.css";

export const metadata: Metadata = {
  title: "Переход по коду — BookTranslate",
  description: "Переход к блоку или объекту книги по его постоянному коду.",
};

/* Переход к блоку или объекту по коду.

   Код вида `CH03-B0042` находит блок в книге, `BK01-CH03-B0042` — где
   угодно в пространстве: в какой бы главе и на какой странице списка он
   ни стоял. Найденный блок открывается на своей странице главы и
   подсвечивается. Код объекта — `CH03-FIG001` — открывает его карточку.

   Блок, выведенный из действия, в текущей версии мастера места не имеет —
   но и «не найдено» он не стал: на него ссылаются прежние версии. Тогда
   здесь показывается он сам. */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const CODE = /^(?:BK\d+-)?CH\d+-B\d+$/i;
// Код объекта: рисунок, таблица, формула, листинг.
const OBJECT_CODE = /^(?:BK\d+-)?CH\d+-(?:FIG|TBL|EQ|CODE)\d+$/i;

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

  const here = `/app/find?code=${encodeURIComponent(code)}`;

  if (OBJECT_CODE.test(code)) {
    const object = await load<FoundObject>(
      inBook !== undefined
        ? `/books/${inBook}/objects/${encodeURIComponent(code)}`
        : `/objects/lookup?code=${encodeURIComponent(code)}`,
      here,
    );

    if (object.error !== undefined) {
      return <Answer>{object.error}</Answer>;
    }

    const { book_id, chapter_id, object_id } = object.data;
    redirect(`/app/books/${book_id}/chapters/${chapter_id}/objects/${object_id}`);
  }

  if (!CODE.test(code)) {
    return (
      <Answer>
        Код выглядит так: блок — <b>CH03-B0042</b>, объект — <b>CH03-FIG001</b>. Вне книги — с
        её кодом: <b>BK01-CH03-B0042</b>.
      </Answer>
    );
  }
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
      <h2>Переход по коду</h2>
      <p className="tile__empty">{children}</p>
    </section>
  );
}
