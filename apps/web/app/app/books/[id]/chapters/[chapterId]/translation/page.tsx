import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import {
  load,
  type Book,
  type BookStructure,
  type ChapterBlock,
  type ChapterBlockPage,
  type ChapterTranslation,
} from "../../../../../../lib/work";
import {
  KIND_ONE,
  REVISION_ORIGIN_CHIP,
  REVISION_ORIGIN_LABEL,
  plural,
  thousands,
} from "../../../../../labels";
import "../../../../../work.css";
import "../../../../../ui/ui.css";
import "../../../../books.css";
import { CopyId } from "../../../../../ui/copy-id";
import { Pager } from "../../../../../ui/pager";
import { paramsOf, wholeNumber } from "../../../../../ui/query";
import { DataTable, type Column } from "../../../../../ui/table";
import { ExportLinks } from "../../../../export-links";

export const metadata: Metadata = {
  title: "Перевод главы — BookTranslate",
  description: "Блоки главы рядом с их текущими редакциями перевода.",
};

/* Перевод главы: исходник и текущая редакция рядом, блок за блоком.

   Текст здесь только читают: редакция неизменяема, и всё, что с ней можно
   сделать, — посмотреть историю и попросить вариант. Это на странице блока. */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const PER_PAGE = 50;
const OFFSET_MAX = 1_000_000;

export default async function ChapterTranslationPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string; chapterId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id, chapterId } = await params;

  if (!UUID.test(id) || !UUID.test(chapterId)) {
    notFound();
  }

  const query = paramsOf(await searchParams);
  const chapterPath = `/app/books/${id}/chapters/${chapterId}`;
  const here = `${chapterPath}/translation`;
  const offset = wholeNumber(query.get("offset"), 0, OFFSET_MAX);

  const [book, structure, page, state] = await Promise.all([
    load<Book>(`/books/${id}`, here),
    load<BookStructure>(`/books/${id}/chapters`, here),
    load<ChapterBlockPage>(
      `/chapters/${chapterId}/translation/blocks?limit=${PER_PAGE}&offset=${offset}`,
      here,
    ),
    // Счёт по всей главе, а не по открытой странице: непереведённое может быть дальше.
    load<ChapterTranslation>(`/chapters/${chapterId}/translation`, here),
  ]);

  const chapter = structure.data?.chapters.find((item) => item.id === chapterId);

  if (book.error !== undefined || page.error !== undefined || chapter === undefined) {
    return (
      <section className="tile">
        <h2>Перевод главы</h2>
        <p className="tile__empty">{book.error ?? page.error ?? "Глава не найдена"}</p>
        <div className="tile__foot">
          <Link className="btn btn--ghost btn--small" href={chapterPath}>
            К главе
          </Link>
        </div>
      </section>
    );
  }

  const prefix = chapter.code !== null ? `${chapter.code}-` : "";

  return (
    <>
      <header className="wk-head">
        <div>
          <p className="wk-crumbs">
            <Link href="/app/books">Книги</Link>
            <span aria-hidden="true"> · </span>
            <Link href={`/app/books/${id}`}>{book.data.title}</Link>
            <span aria-hidden="true"> · </span>
            <Link href={chapterPath}>{chapter.title ?? `Глава ${chapter.ordinal}`}</Link>
          </p>
          <h1>Перевод главы</h1>
          <p className="tile__note">
            {thousands(page.data.total)} {plural(page.data.total, "блок", "блока", "блоков")}
            {" · "}у каждого своя история редакций: прежний текст не перезаписывается
          </p>
        </div>
      </header>

      {state.data !== undefined && state.data.translated > 0 && (
        <section className="tile">
          <h3>Рабочая выгрузка</h3>
          <p className="tile__note">
            Текущие редакции одним файлом, у каждого блока его код: чтобы обсуждать правки. Читателю
            такой файл не отдают: чистый файл даёт читательская версия из утверждённого выпуска.
          </p>
          <ExportLinks
            path={`/api/chapters/${chapterId}/export`}
            formats={["docx", "markdown", "text"]}
            draft={state.data.pending > 0}
            working
          />
        </section>
      )}

      <section className="tile">
        <DataTable
          caption="Блоки главы и их текущие редакции"
          columns={columns(here, prefix)}
          rows={page.data.items}
          rowAnchor={(block) => block.code}
          empty="В главе нет блоков: сначала извлеките мастер."
        />
        <Pager
          total={page.data.total}
          limit={PER_PAGE}
          offset={offset}
          path={here}
          params={query}
        />
      </section>
    </>
  );
}

function columns(here: string, prefix: string): Column<ChapterBlock>[] {
  return [
    {
      title: "Block ID",
      cell: (block) => <CopyId value={`${prefix}${block.code}`} title="код блока" />,
    },
    {
      title: "Исходник",
      cell: (block) =>
        block.kind === "code" ? (
          <pre className="bk-block-code">{block.source_text}</pre>
        ) : (
          <span className="bk-block-text">{block.source_text}</span>
        ),
    },
    {
      title: "Перевод",
      cell: (block) =>
        block.current === null ? (
          <span className="tile__note">ещё не переведён</span>
        ) : block.kind === "code" ? (
          <pre className="bk-block-code">{block.current.text}</pre>
        ) : (
          <span className="bk-block-text">{block.current.text}</span>
        ),
    },
    {
      title: "Откуда",
      secondary: true,
      cell: (block) =>
        block.current === null ? (
          <span className="tile__note">{KIND_ONE[block.kind] ?? block.kind}</span>
        ) : (
          <span className={REVISION_ORIGIN_CHIP[block.current.origin] ?? "chip chip--info"}>
            {REVISION_ORIGIN_LABEL[block.current.origin] ?? block.current.origin}
          </span>
        ),
    },
    {
      title: "Редакции",
      cell: (block) => (
        <span className="bk-block-id">
          <Link className="tile__note" href={`${here}/${block.id}`}>
            {block.current === null ? "открыть" : `v${block.current.revision_no}`}
          </Link>
          {block.formal_checked && <span className="chip chip--ok">формально</span>}
          {block.semantic_checked && <span className="chip chip--ok">смысл</span>}
          {block.variants > 0 && (
            <span className="chip chip--warn">
              {block.variants} {plural(block.variants, "вариант", "варианта", "вариантов")}
            </span>
          )}
        </span>
      ),
    },
  ];
}
