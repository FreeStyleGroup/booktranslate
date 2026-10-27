import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { currentUser } from "../../../../../../lib/current-user";
import { organizationId } from "../../../../../../lib/session";
import {
  load,
  type Book,
  type GlossaryVersionDetail,
  type ImpactedBlock,
  type ImpactPage,
  type TermChange,
  type TermRecord,
  type VersionTerm,
  type VersionTermPage,
} from "../../../../../../lib/work";
import {
  FIRST_USE_RULE,
  GLOSSARY_KIND,
  GLOSSARY_STATUS,
  TERM_CHANGE_CHIP,
  TERM_CHANGE_LABEL,
  VERSION_STATUS_CHIP,
  VERSION_STATUS_LABEL,
  shortHash,
  thousands,
  when,
} from "../../../../../labels";
import "../../../../../work.css";
import "../../../../../ui/ui.css";
import "../../../../books.css";
import { CopyId } from "../../../../../ui/copy-id";
import { Pager } from "../../../../../ui/pager";
import { linkTo, oneOf, paramsOf, wholeNumber } from "../../../../../ui/query";
import { DataTable, type Column } from "../../../../../ui/table";
import { ApproveForm } from "../../approve-form";

export const metadata: Metadata = {
  title: "Версия глоссария — BookTranslate",
  description: "Снимок терминов, решение по нему и блоки книги, которые задевают изменения.",
};

/* Версия глоссария: снимок, решение и то, что изменится.

   Черновик утверждают ровно таким, каким его видят здесь: он не
   пересобирается при утверждении. Поэтому рядом с кнопкой — всё, что
   нужно для решения: что мешает, что изменилось против действующей версии
   и какие блоки книги эти изменения задевают. */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const PER_PAGE = 100;
const OFFSET_MAX = 1_000_000;
const QUERY_MAX = 300;

// Кто утверждает. Тот же набор, что в API.
const APPROVING = new Set(["owner", "admin", "manager"]);

const TERMS_TAB = "terms";
const IMPACT_TAB = "impact";

export default async function VersionPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string; versionId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id, versionId } = await params;

  if (!UUID.test(id) || !UUID.test(versionId)) {
    notFound();
  }

  const query = paramsOf(await searchParams);
  const here = `/app/books/${id}/terminology/versions/${versionId}`;
  const tab = oneOf(query.get("tab"), [TERMS_TAB, IMPACT_TAB], TERMS_TAB);
  const offset = wholeNumber(query.get("offset"), 0, OFFSET_MAX);
  const search = (query.get("q") ?? "").trim().slice(0, QUERY_MAX);
  const changeId = query.get("change");
  const onlyChange = changeId !== null && UUID.test(changeId) ? changeId : null;

  const [book, found, changes, me, organization] = await Promise.all([
    load<Book>(`/books/${id}`, here),
    load<GlossaryVersionDetail>(`/glossary-versions/${versionId}`, here),
    load<TermChange[]>(`/glossary-versions/${versionId}/changes`, here),
    currentUser(here),
    organizationId(),
  ]);

  if (book.error !== undefined || found.error !== undefined || changes.error !== undefined) {
    return (
      <section className="tile">
        <h2>Версия глоссария</h2>
        <p className="tile__empty">{book.error ?? found.error ?? changes.error}</p>
        <div className="tile__foot">
          <Link className="btn btn--ghost btn--small" href={`/app/books/${id}/terminology`}>
            К терминологии книги
          </Link>
        </div>
      </section>
    );
  }

  const version = found.data;
  const membership =
    me?.memberships.find((item) => item.organization_id === organization) ?? me?.memberships[0];
  const canApprove = membership !== undefined && APPROVING.has(membership.role);

  // Грузится только открытая вкладка: у версии на тысячи терминов вторая
  // страница списка — лишний запрос на каждое открытие.
  const [impact, terms] = await Promise.all([
    tab === IMPACT_TAB
      ? load<ImpactPage>(
          `/glossary-versions/${versionId}/impact?limit=${PER_PAGE}&offset=${offset}` +
            (onlyChange !== null ? `&change_id=${onlyChange}` : ""),
          here,
        )
      : undefined,
    tab === TERMS_TAB
      ? load<VersionTermPage>(
          `/glossary-versions/${versionId}/terms?limit=${PER_PAGE}&offset=${offset}` +
            (search !== "" ? `&query=${encodeURIComponent(search)}` : ""),
          here,
        )
      : undefined,
  ]);

  const area = version.chapter_id === null ? "вся книга" : `глава ${version.chapter_code ?? ""}`;
  const findBlock = (code: string) => `/app/find?book=${id}&code=${encodeURIComponent(code)}`;

  return (
    <>
      <header className="wk-head">
        <div>
          <p className="wk-crumbs">
            <Link href="/app/books">Книги</Link>
            <span aria-hidden="true"> · </span>
            <Link href={`/app/books/${id}`}>{book.data.title}</Link>
            <span aria-hidden="true"> · </span>
            <Link href={`/app/books/${id}/terminology`}>Терминология</Link>
          </p>

          <h1>Глоссарий {version.label}</h1>

          <p className="tile__note">
            {area} · собрана {when(version.created_at)} · {thousands(version.term_count)} терминов
          </p>
        </div>

        <div className="bk-head__side">
          <CopyId
            value={version.checksum}
            title="контрольную сумму версии"
            label={shortHash(version.checksum)}
          />
          <span className={VERSION_STATUS_CHIP[version.status] ?? "chip chip--info"}>
            {VERSION_STATUS_LABEL[version.status] ?? version.status}
          </span>
        </div>
      </header>

      <section className="tile">
        <h3>Решение</h3>

        {version.status === "approved" && (
          <p>
            Утверждена {version.approved_at !== null && when(version.approved_at)} — по ней
            переводят {version.chapter_id === null ? "главы книги" : "эту главу"}.
            {version.empty_reason !== null && <> Терминов нет: «{version.empty_reason}».</>}
          </p>
        )}

        {version.status === "superseded" && (
          <p className="tile__note">
            Заменена
            {version.superseded_by_id !== null && (
              <>
                {" "}
                <Link href={`/app/books/${id}/terminology/versions/${version.superseded_by_id}`}>
                  следующей версией
                </Link>
              </>
            )}{" "}
            и в работу больше не идёт. Снимок остаётся: по нему восстанавливают, с каким глоссарием
            переводилось раньше.
          </p>
        )}

        {version.status === "draft" && version.blockers.length > 0 && (
          <>
            <p>Утвердить пока нельзя:</p>
            <ul className="bk-gate__list">
              {version.blockers.map((item, index) => (
                <li key={`${item.code}-${index}`}>{item.message}</li>
              ))}
            </ul>
          </>
        )}

        {version.status === "draft" && version.blockers.length === 0 && (
          <p className="tile__note">
            Причин, мешающих утверждению, нет. Утверждается ровно этот снимок — термины ниже, с этой
            контрольной суммой; правки словаря после сборки в него не входят.
          </p>
        )}

        {version.status === "draft" &&
          version.blockers.length === 0 &&
          (canApprove ? (
            <ApproveForm
              bookId={id}
              versionId={version.id}
              label={version.label}
              empty={version.term_count === 0}
            />
          ) : (
            <p className="tile__note">
              Утвердить версию может менеджер или администратор пространства.
            </p>
          ))}
      </section>

      <section className="tile">
        <div className="tile__head">
          <h3>Что изменилось</h3>
          {version.base_id !== null && (
            <span className="tile__note">
              против действующей версии · {thousands(version.impacted_blocks)} затронутых блоков
            </span>
          )}
        </div>

        {version.base_id === null ? (
          <p className="tile__empty">
            Первая версия для этой области — сравнивать не с чем, и переводить по прежнему глоссарию
            никто не мог.
          </p>
        ) : (
          <DataTable
            caption="Изменения обязательных терминов"
            columns={changeColumns(here, query)}
            rows={changes.data}
            empty="Обязательные термины не изменились — перепроверять нечего."
          />
        )}
      </section>

      <nav className="bk-tabs" aria-label="Содержимое версии">
        {[
          { type: TERMS_TAB, title: "Термины", count: version.term_count },
          { type: IMPACT_TAB, title: "Затронутые блоки", count: version.impacted_blocks },
        ].map((item) => (
          <Link
            key={item.type}
            className={item.type === tab ? "is-active" : undefined}
            aria-current={item.type === tab ? "page" : undefined}
            href={linkTo(here, query, {
              tab: item.type === TERMS_TAB ? null : item.type,
              offset: null,
              change: null,
              q: null,
            })}
          >
            {item.title}
            <span className="bk-tabs__count">{thousands(item.count)}</span>
          </Link>
        ))}
      </nav>

      {impact !== undefined && (
        <section className="tile">
          {impact.error !== undefined ? (
            <p className="tile__empty">{impact.error}</p>
          ) : (
            <>
              {onlyChange !== null && (
                <p className="tile__note">
                  Только блоки одного изменения ·{" "}
                  <Link href={linkTo(here, query, { change: null, offset: null })}>все</Link>
                </p>
              )}
              <DataTable
                caption="Блоки книги, которые задевают изменения версии"
                columns={impactColumns(findBlock)}
                rows={impact.data.items.map((item) => ({ ...item, id: item.block.id }))}
                empty="Изменения не задевают ни одного блока книги."
              />
              <Pager
                total={impact.data.total}
                limit={PER_PAGE}
                offset={offset}
                path={here}
                params={query}
              />
            </>
          )}
        </section>
      )}

      {terms !== undefined && (
        <section className="tile">
          {terms.error !== undefined ? (
            <p className="tile__empty">{terms.error}</p>
          ) : (
            <>
              <form className="bk-search" action={here}>
                <input type="hidden" name="tab" value={TERMS_TAB} />
                <input
                  type="search"
                  name="q"
                  defaultValue={search}
                  maxLength={QUERY_MAX}
                  placeholder="Термин или перевод"
                  aria-label="Найти термин в версии"
                />
                <button className="btn btn--ghost btn--small" type="submit">
                  Найти
                </button>
              </form>
              <DataTable
                caption={`Термины версии ${version.label}`}
                columns={TERM_COLUMNS}
                rows={terms.data.items}
                empty={
                  search !== ""
                    ? "Под такой запрос в версии терминов нет."
                    : "В версии нет терминов — это решение «терминов нет»."
                }
              />
              <Pager
                total={terms.data.total}
                limit={PER_PAGE}
                offset={offset}
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

/** Решение по термину одной строкой: перевод и, если есть, варианты. */
function Decision({ record }: { record: TermRecord | null }) {
  if (record === null) {
    return <span className="tile__note">—</span>;
  }

  return (
    <span>
      {record.target_term}
      {!record.mandatory && <span className="bk-variants">необязательный</span>}
      {record.allowed_variants.length > 0 && (
        <span className="bk-variants">варианты: {record.allowed_variants.join("; ")}</span>
      )}
      {record.status !== "confirmed" && (
        <span className="bk-variants">{GLOSSARY_STATUS[record.status] ?? record.status}</span>
      )}
      {record.first_use_rule !== "none" && (
        <span className="bk-variants">
          {FIRST_USE_RULE[record.first_use_rule]?.toLowerCase() ?? record.first_use_rule}
        </span>
      )}
    </span>
  );
}

function changeColumns(here: string, query: URLSearchParams): Column<TermChange>[] {
  return [
    { title: "Термин", cell: (change) => <b>{change.source_term}</b> },
    {
      title: "Изменение",
      // На узком экране вид изменения читается по столбцам «было» и «стало».
      secondary: true,
      cell: (change) => (
        <span className={TERM_CHANGE_CHIP[change.kind] ?? "chip chip--info"}>
          {TERM_CHANGE_LABEL[change.kind] ?? change.kind}
        </span>
      ),
    },
    { title: "Было", cell: (change) => <Decision record={change.before} /> },
    { title: "Стало", cell: (change) => <Decision record={change.after} /> },
    {
      title: "Блоков",
      numeric: true,
      cell: (change) =>
        change.blocks === 0 ? (
          <span className="tile__note">0</span>
        ) : (
          <Link
            href={linkTo(here, query, {
              tab: IMPACT_TAB,
              change: change.id,
              offset: null,
              q: null,
            })}
          >
            {thousands(change.blocks)}
          </Link>
        ),
    },
  ];
}

function impactColumns(
  findBlock: (code: string) => string,
): Column<ImpactedBlock & { id: string }>[] {
  return [
    {
      title: "Block ID",
      cell: (item) => (
        <span className="bk-block-id">
          <Link href={findBlock(item.block.full_code)}>{item.block.full_code}</Link>
          {!item.block.active && <span className="chip chip--warn">выведен</span>}
        </span>
      ),
    },
    { title: "Текст", cell: (item) => <span className="bk-block-text">{item.block.text}</span> },
    {
      title: "Термины",
      cell: (item) => <span className="tile__note">{item.terms.join(", ")}</span>,
    },
  ];
}

const TERM_COLUMNS: Column<VersionTerm>[] = [
  { title: "Термин", cell: (term) => <b>{term.source_term}</b> },
  {
    title: "Перевод",
    cell: (term) => (
      <span>
        {term.target_term}
        {term.allowed_variants.length > 0 && (
          <span className="bk-variants">варианты: {term.allowed_variants.join("; ")}</span>
        )}
      </span>
    ),
  },
  {
    title: "Разряд",
    secondary: true,
    cell: (term) => <span className="tile__note">{GLOSSARY_KIND[term.kind] ?? term.kind}</span>,
  },
  {
    title: "Состояние",
    cell: (term) => (
      <span className="tile__note">
        {GLOSSARY_STATUS[term.status] ?? term.status}
        {term.mandatory ? "" : " · необязательный"}
      </span>
    ),
  },
  {
    title: "Первое употребление",
    secondary: true,
    cell: (term) => (
      <span className="tile__note">
        {term.first_use_rule === "none"
          ? "—"
          : (FIRST_USE_RULE[term.first_use_rule] ?? term.first_use_rule)}
      </span>
    ),
  },
  {
    title: "Область",
    secondary: true,
    cell: (term) => <span className="tile__note">{term.domain ?? "—"}</span>,
  },
];
