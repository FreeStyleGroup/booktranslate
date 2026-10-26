import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { currentUser } from "../../../../../lib/current-user";
import { organizationId } from "../../../../../lib/session";
import {
  load,
  type Block,
  type BlockPage,
  type Book,
  type BookKit,
  type BookStructure,
  type ChapterMaster,
} from "../../../../../lib/work";
import { BOUNDARY_CHIP, BOUNDARY_LABEL, KIND_ONE, thousands, whereIs } from "../../../../labels";
import "../../../../work.css";
import "../../../../ui/ui.css";
import "../../../books.css";
import { CopyId } from "../../../../ui/copy-id";
import { Pager } from "../../../../ui/pager";
import { paramsOf, wholeNumber } from "../../../../ui/query";
import { DataTable, type Column } from "../../../../ui/table";
import { FindBlock } from "../../../find-block";
import { MasterPanel } from "./master-panel";

export const metadata: Metadata = {
  title: "Глава — BookTranslate",
  description: "Мастер главы: неизменяемый исходный текст и блоки с постоянными кодами.",
};

/* Глава: мастер и блоки.

   Мастер — снимок исходного текста главы, который не правится никогда.
   Здесь его смотрят только для чтения: блок за блоком, с постоянным кодом
   отдельным столбцом, рядом — ссылка на визуальный эталон. Ошибка
   извлечения исправляется не правкой, а новой версией с причиной; прежние
   версии остаются и открываются такими, какими были. */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Сколько блоков на странице. Глава — это сотни блоков; читают их подряд,
// и пятьдесят — столько помещается в экран прокруткой без усталости.
const PER_PAGE = 50;
const OFFSET_MAX = 1_000_000;

// Кто извлекает и утверждает мастер. Тот же набор, что в API.
const MANAGING = new Set(["owner", "admin", "manager", "translator"]);

export default async function ChapterPage({
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
  const here = `/app/books/${id}/chapters/${chapterId}`;

  const [book, structure, versions, kit, me, organization] = await Promise.all([
    load<Book>(`/books/${id}`, here),
    load<BookStructure>(`/books/${id}/chapters`, here),
    load<ChapterMaster[]>(`/chapters/${chapterId}/masters`, here),
    load<BookKit>(`/books/${id}/sources`, here),
    currentUser(here),
    organizationId(),
  ]);

  const chapter = structure.data?.chapters.find((item) => item.id === chapterId);

  if (book.error !== undefined || versions.error !== undefined || chapter === undefined) {
    return (
      <section className="tile">
        <h2>Глава</h2>
        <p className="tile__empty">{book.error ?? versions.error ?? "Глава не найдена"}</p>
        <div className="tile__foot">
          <Link className="btn btn--ghost btn--small" href={`/app/books/${id}/structure`}>
            К структуре книги
          </Link>
        </div>
      </section>
    );
  }

  const membership =
    me?.memberships.find((item) => item.organization_id === organization) ?? me?.memberships[0];
  const canManage = membership !== undefined && MANAGING.has(membership.role);

  const current = versions.data[0];
  const requested = query.get("version");
  const shown = versions.data.find((master) => master.id === requested) ?? current;
  const offset = wholeNumber(query.get("offset"), 0, OFFSET_MAX);

  const blocks =
    shown === undefined
      ? undefined
      : await load<BlockPage>(`/masters/${shown.id}/blocks?limit=${PER_PAGE}&offset=${offset}`, here);

  // Визуальный эталон — PDF рядом с основным источником. Открывается во
  // вкладке; другой формат эталоном для просмотра не годится.
  const reference = kit.data?.sources.find(
    (source) => source.source_role === "visual_reference" && source.source_format === "pdf",
  );

  return (
    <>
      <header className="wk-head">
        <div>
          <p className="wk-crumbs">
            <Link href="/app/books">Книги</Link>
            <span aria-hidden="true"> · </span>
            <Link href={`/app/books/${id}`}>{book.data.title}</Link>
            <span aria-hidden="true"> · </span>
            <Link href={`/app/books/${id}/structure`}>Структура</Link>
          </p>

          <h1>{chapter.title ?? "Без названия"}</h1>

          <p className="tile__note">
            {[
              `глава ${chapter.ordinal}`,
              whereIs(chapter.locator),
              chapter.boundary_version > 1 ? `границы v${chapter.boundary_version}` : null,
            ]
              .filter((part) => part !== null)
              .join(" · ")}
          </p>
        </div>

        <div className="bk-head__side">
          {chapter.code !== null && <CopyId value={chapter.code} title="код главы" />}
          <span className={BOUNDARY_CHIP[chapter.boundary_status] ?? "chip chip--info"}>
            {BOUNDARY_LABEL[chapter.boundary_status] ?? chapter.boundary_status}
          </span>
        </div>
      </header>

      <MasterPanel
        bookId={id}
        chapterId={chapterId}
        approvedBoundaries={chapter.boundary_status === "approved"}
        versions={versions.data}
        shownId={shown?.id ?? null}
        canManage={canManage}
      />

      {shown !== undefined && current !== undefined && shown.id !== current.id && (
        // Прежняя версия открыта нарочно — но это должно быть видно сразу,
        // а не по мелкому номеру в углу.
        <p className="bk-mismatch" role="status">
          <span aria-hidden="true">⚠</span>
          <span>
            Открыта прежняя версия мастера {shown.label}. Текущая — {current.label}:{" "}
            <Link href={here}>перейти к ней</Link>.
          </span>
        </p>
      )}

      {shown !== undefined && blocks !== undefined && (
        <section className="tile">
          <div className="tile__head">
            <h3>Блоки {shown.label}</h3>
            <span className="bk-tools__side">
              {reference !== undefined && (
                <a
                  className="btn btn--ghost btn--small"
                  href={`/api/documents/${reference.id}/view`}
                  target="_blank"
                  rel="noopener"
                >
                  Визуальный эталон ↗
                </a>
              )}
              <FindBlock bookId={id} />
            </span>
          </div>

          {blocks.error !== undefined ? (
            <p className="tile__empty">{blocks.error}</p>
          ) : (
            <>
              <DataTable
                caption={`Блоки главы, версия мастера ${shown.label}`}
                columns={COLUMNS}
                rows={blocks.data.items}
                rowAnchor={(block) => block.code}
                empty="В этой версии мастера нет блоков."
              />

              <Pager
                total={blocks.data.total}
                limit={blocks.data.limit}
                offset={blocks.data.offset}
                path={here}
                params={query}
              />
            </>
          )}
        </section>
      )}
    </>
  );
}

const COLUMNS: Column<Block>[] = [
  {
    title: "Block ID",
    // Код — отдельным столбцом и копируемый: по нему блок называют в
    // переписке и в замечаниях, и находят из любого места книги.
    cell: (block) => (
      <span className="bk-block-id">
        <CopyId value={block.full_code} title="код блока" />
        {!block.active && <span className="chip chip--warn">выведен</span>}
      </span>
    ),
  },
  {
    title: "Текст",
    cell: (block) =>
      block.kind === "code" ? (
        // Листинг — моноширинным и с переносами строк как в исходнике:
        // отступы в нём и есть текст мастера.
        <pre className="bk-block-code">{block.source_text}</pre>
      ) : (
        <span className="bk-block-text">{block.source_text}</span>
      ),
  },
  {
    title: "Вид",
    secondary: true,
    cell: (block) => <span className="tile__note">{KIND_ONE[block.kind] ?? block.kind}</span>,
  },
  {
    title: "Из блока",
    secondary: true,
    // Предок — блок прежней версии, из которого этот получился правкой или
    // разделением. Прежний код не переиспользуется — родство видно здесь.
    cell: (block) =>
      block.parent_code === null ? (
        <span className="tile__note">—</span>
      ) : (
        <span className="tile__note">{block.parent_code}</span>
      ),
  },
  {
    title: "Частей",
    numeric: true,
    secondary: true,
    cell: (block) => <span className="tile__note">{thousands(block.chunks)}</span>,
  },
];
