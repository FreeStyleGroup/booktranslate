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
  type BookObject,
  type BookStructure,
  type ChapterMaster,
  type TerminologyGate,
} from "../../../../../lib/work";
import {
  BOUNDARY_CHIP,
  BOUNDARY_LABEL,
  KIND_ONE,
  OBJECT_ONE,
  OBJECT_TABS,
  thousands,
  whereIs,
} from "../../../../labels";
import "../../../../work.css";
import "../../../../ui/ui.css";
import "../../../books.css";
import { CopyId } from "../../../../ui/copy-id";
import { Pager } from "../../../../ui/pager";
import { linkTo, oneOf, paramsOf, wholeNumber } from "../../../../ui/query";
import { DataTable, type Column } from "../../../../ui/table";
import { FindBlock } from "../../../find-block";
import { GatePanel } from "../../../gate-panel";
import { MasterPanel } from "./master-panel";
import { ObjectsTab } from "./objects-tab";

export const metadata: Metadata = {
  title: "Глава — BookTranslate",
  description: "Мастер главы: неизменяемый исходный текст и блоки с постоянными кодами.",
};

/* Глава: мастер, блоки и объекты.

   Мастер — снимок исходного текста главы, который не правится никогда.
   Здесь его смотрят только для чтения: блок за блоком, с постоянным кодом
   отдельным столбцом, рядом — ссылка на визуальный эталон. Ошибка
   извлечения исправляется не правкой, а новой версией с причиной; прежние
   версии остаются и открываются такими, какими были.

   Рисунки, таблицы, формулы и код — на своих вкладках, у каждого объекта
   свой постоянный код. Вкладка — в адресе: ссылка на «таблицы главы 3»
   открывается таблицами. */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Сколько блоков на странице. Глава — это сотни блоков; читают их подряд,
// и пятьдесят — столько помещается в экран прокруткой без усталости.
const PER_PAGE = 50;
const OFFSET_MAX = 1_000_000;

// Кто извлекает и утверждает мастер. Тот же набор, что в API.
const MANAGING = new Set(["owner", "admin", "manager", "translator"]);

const TEXT_TAB = "text";
const TABS = [TEXT_TAB, ...OBJECT_TABS.map((tab) => tab.type)];

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

  const [book, structure, versions, kit, gate, me, organization] = await Promise.all([
    load<Book>(`/books/${id}`, here),
    load<BookStructure>(`/books/${id}/chapters`, here),
    load<ChapterMaster[]>(`/chapters/${chapterId}/masters`, here),
    load<BookKit>(`/books/${id}/sources`, here),
    load<TerminologyGate>(`/chapters/${chapterId}/terminology/gate`, here),
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
  const tab = oneOf(query.get("tab"), TABS, TEXT_TAB);

  // Объекты версии нужны на любой вкладке: по ним считаются вкладки, а у
  // блоков виден объект, которому блок принадлежит.
  const [blocks, objects] =
    shown === undefined
      ? [undefined, undefined]
      : await Promise.all([
          tab === TEXT_TAB
            ? load<BlockPage>(`/masters/${shown.id}/blocks?limit=${PER_PAGE}&offset=${offset}`, here)
            : undefined,
          load<BookObject[]>(`/masters/${shown.id}/objects`, here),
        ]);

  const owners = ownersOf(objects?.data ?? []);
  const tabInfo = OBJECT_TABS.find((item) => item.type === tab);

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

      {/* Готова ли глава к переводу по терминам — до самого перевода, а не
          отказом на кнопке «Перевести». */}
      {gate.data !== undefined && <GatePanel gate={gate.data} bookId={id} termsLink />}

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

      {shown !== undefined && (
        <nav className="bk-tabs" aria-label="Содержимое главы">
          {[{ type: TEXT_TAB, title: "Текст" }, ...OBJECT_TABS].map((item) => {
            const count =
              item.type === TEXT_TAB
                ? shown.block_count
                : (objects?.data ?? []).filter((object) => object.type === item.type).length;

            return (
              <Link
                key={item.type}
                className={item.type === tab ? "is-active" : undefined}
                aria-current={item.type === tab ? "page" : undefined}
                href={linkTo(here, query, {
                  tab: item.type === TEXT_TAB ? null : item.type,
                  offset: null,
                })}
              >
                {item.title}
                <span className="bk-tabs__count">{thousands(count)}</span>
              </Link>
            );
          })}
        </nav>
      )}

      {shown !== undefined && tabInfo !== undefined && objects !== undefined && (
        <section className="tile">
          <div className="tile__head">
            <h3>
              {tabInfo.title} {shown.label}
            </h3>
          </div>
          {objects.error !== undefined ? (
            <p className="tile__empty">{objects.error}</p>
          ) : (
            <ObjectsTab
              type={tabInfo.type}
              title={`${tabInfo.title} главы, версия мастера ${shown.label}`}
              objects={objects.data.filter((item) => item.type === tabInfo.type)}
              cardPath={`${here}/objects`}
              empty={tabInfo.empty}
            />
          )}
        </section>
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
                columns={columns(owners, `${here}/objects`)}
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

type Owner = { object: BookObject; caption: boolean };

/** Чей блок: ячейка таблицы, текст листинга или подпись объекта. */
function ownersOf(objects: BookObject[]): Map<string, Owner> {
  const owners = new Map<string, Owner>();

  for (const object of objects) {
    for (const code of object.content_codes) {
      owners.set(code, { object, caption: false });
    }
    if (object.caption_code !== null) {
      owners.set(object.caption_code, { object, caption: true });
    }
  }

  return owners;
}

function columns(owners: Map<string, Owner>, cardPath: string): Column<Block>[] {
  return [...COLUMNS.slice(0, 2), ownerColumn(owners, cardPath), ...COLUMNS.slice(2)];
}

function ownerColumn(owners: Map<string, Owner>, cardPath: string): Column<Block> {
  return {
    title: "Объект",
    secondary: true,
    // Ячейка таблицы переводится как текст, но стоит в сетке; листинг не
    // переводится вовсе. Это видно здесь, у самого блока.
    cell: (block) => {
      const owner = owners.get(block.full_code);

      if (owner === undefined) {
        return <span className="tile__note">—</span>;
      }

      return (
        <Link className="tile__note" href={`${cardPath}/${owner.object.id}`}>
          {owner.caption ? "подпись " : ""}
          {owner.object.code}
          <span className="bk-owner-kind"> · {OBJECT_ONE[owner.object.type]}</span>
        </Link>
      );
    },
  };
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
