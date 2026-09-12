import type { Metadata } from "next";
import Link from "next/link";

import { currentUser } from "../../lib/current-user";
import { organizationId } from "../../lib/session";
import {
  load,
  type GlossaryPage as Page,
  type GlossaryUpload,
  type Project,
  type Suggestions as SuggestionList,
} from "../../lib/work";
import { GLOSSARY_KIND, GLOSSARY_STATUS, plural, thousands } from "../labels";
import type { WorkspaceSettings } from "../settings/actions";
import "../work.css";
import "../settings/settings.css";
import "./glossary.css";
import { AddTerm } from "./add-term";
import { ImportForm } from "./import-form";
import { SuggestionsBlock } from "./suggestions";
import { TermList } from "./term-list";

export const metadata: Metadata = {
  title: "Словарь — BookTranslate",
  description: "Решения по терминам: как это называется у заказчика.",
};

/* Словарь рабочего пространства.

   Здесь лежат решения — «у этого заказчика valve — клапан», — а не
   справки о том, что такое valve. Решение уходит модели подсказкой и
   проверяется в её ответе; неустоявшееся только подсказывает.

   Три источника записей: руками, загрузкой файла и из общего словаря
   площадки. Последний — подсказки по тематике пространства, и в словарь
   они попадают только после того, как человек их принял. */

const PAGE = 100;

// Языковая пара как значение формы: «en→ru». Пара берётся из проектов —
// словарь без проекта не к чему применять.
export type Pair = { value: string; source: string; target: string };

const KINDS = Object.keys(GLOSSARY_KIND);
const STATUSES = Object.keys(GLOSSARY_STATUS);

function parseOffset(value: string | undefined): number {
  const parsed = Number.parseInt(value ?? "", 10);

  return Number.isInteger(parsed) && parsed > 0 ? parsed : 0;
}

function pageHref(query: string, kind: string, status: string, offset: number): string {
  const parameters = new URLSearchParams();

  if (query !== "") {
    parameters.set("query", query);
  }

  if (kind !== "") {
    parameters.set("kind", kind);
  }

  if (status !== "") {
    parameters.set("status", status);
  }

  if (offset > 0) {
    parameters.set("offset", String(offset));
  }

  const suffix = parameters.toString();

  return suffix === "" ? "/app/glossary" : `/app/glossary?${suffix}`;
}

export default async function GlossaryPage({
  searchParams,
}: {
  searchParams: Promise<{ query?: string; kind?: string; status?: string; offset?: string }>;
}) {
  const { query = "", kind = "", status = "", offset: offsetParam } = await searchParams;
  const offset = parseOffset(offsetParam);
  const here = pageHref(query, kind, status, offset);

  const parameters = new URLSearchParams();
  parameters.set("limit", String(PAGE));
  parameters.set("offset", String(offset));

  if (query !== "") {
    parameters.set("query", query);
  }

  if (KINDS.includes(kind)) {
    parameters.set("kind", kind);
  }

  if (STATUSES.includes(status)) {
    parameters.set("status", status);
  }

  const [page, projects, uploads, suggestions, workspace, me, organization] = await Promise.all([
    load<Page>(`/glossary?${parameters.toString()}`, here),
    load<Project[]>("/projects?limit=200", here),
    load<GlossaryUpload[]>("/glossary/uploads", here),
    load<SuggestionList>("/glossary/suggestions", here),
    load<WorkspaceSettings>("/settings/workspace", here),
    currentUser(here),
    organizationId(),
  ]);

  if (page.error !== undefined) {
    return (
      <section className="tile">
        <h2>Словарь</h2>
        <p className="tile__empty">{page.error}</p>
      </section>
    );
  }

  // Роль смотрящего: разрешение на общий словарь даёт владелец или
  // администратор, остальные видят его состояние.
  const membership =
    me?.memberships.find((item) => item.organization_id === organization) ?? me?.memberships[0];
  const manages = membership?.role === "owner" || membership?.role === "admin";
  const edits = manages || membership?.role === "manager" || membership?.role === "translator";

  const pairs = distinctPairs(projects.data ?? []);
  const filtered = query !== "" || kind !== "" || status !== "";
  const more = offset + page.data.items.length < page.data.total;

  return (
    <>
      <header className="wk-head gl-head">
        <div>
          <h1>Словарь</h1>
          <p className="tile__note">
            Как это называется у вас. Подтверждённый термин уходит модели
            требованием и проверяется в переводе; предложенный — только
            подсказывает.
          </p>
        </div>
      </header>

      {suggestions.data !== undefined && (
        <SuggestionsBlock
          suggestions={suggestions.data}
          subjectTitle={subjectTitle(workspace.data, suggestions.data.subject)}
          edits={edits}
        />
      )}

      {edits && (
        <div className="gl-tools">
          <AddTerm pairs={pairs} />
          <ImportForm
            pairs={pairs}
            manages={manages}
            sharing={workspace.data?.share_glossary ?? false}
            uploads={uploads.data ?? []}
          />
        </div>
      )}

      <section className="tile gl-block">
        <div className="tile__head">
          <h3>Термины</h3>
          <span className="tile__note">
            {filtered ? "по отбору " : "всего "}
            {thousands(page.data.total)}
          </span>
        </div>

        <form className="gl-filters" method="get">
          <input
            type="search"
            name="query"
            defaultValue={query}
            placeholder="Термин или перевод"
            aria-label="Поиск по словарю"
          />
          <select name="kind" defaultValue={kind} aria-label="Разряд">
            <option value="">Любой разряд</option>
            {KINDS.map((value) => (
              <option key={value} value={value}>
                {GLOSSARY_KIND[value]}
              </option>
            ))}
          </select>
          <select name="status" defaultValue={status} aria-label="Состояние">
            <option value="">Любое состояние</option>
            {STATUSES.map((value) => (
              <option key={value} value={value}>
                {GLOSSARY_STATUS[value]}
              </option>
            ))}
          </select>
          <button className="btn btn--ghost btn--small" type="submit">
            Показать
          </button>
          {filtered && (
            <Link className="btn btn--ghost btn--small" href="/app/glossary">
              Сбросить
            </Link>
          )}
        </form>

        {page.data.items.length === 0 ? (
          <p className="tile__empty">
            {filtered
              ? "По этому отбору ничего нет."
              : pairs.length === 0
                ? "Словарь пуст. Сначала заведите проект — термины привязаны к языковой паре."
                : "Словарь пуст. Заведите термин, загрузите файл или примите подсказки."}
          </p>
        ) : (
          <TermList terms={page.data.items} edits={edits} />
        )}

        {(offset > 0 || more) && (
          <nav className="gl-pager" aria-label="Страницы словаря">
            <span className="tile__note">
              Показаны {offset + 1}–{offset + page.data.items.length} из{" "}
              {thousands(page.data.total)}
            </span>
            <div className="wk-actions">
              {offset > 0 && (
                <Link
                  className="btn btn--ghost btn--small"
                  href={pageHref(query, kind, status, Math.max(0, offset - PAGE))}
                >
                  ← Назад
                </Link>
              )}
              {more && (
                <Link
                  className="btn btn--ghost btn--small"
                  href={pageHref(query, kind, status, offset + PAGE)}
                >
                  Дальше →
                </Link>
              )}
            </div>
          </nav>
        )}

        {pairs.length > 1 && (
          <p className="tile__note wk-seg__foot">
            В пространстве {pairs.length} {plural(pairs.length, "языковая пара", "языковые пары", "языковых пар")}
            : термин действует только в своей.
          </p>
        )}
      </section>
    </>
  );
}

function distinctPairs(projects: Project[]): Pair[] {
  const seen = new Map<string, Pair>();

  for (const project of projects) {
    const value = `${project.source_language}→${project.target_language}`;

    if (!seen.has(value)) {
      seen.set(value, {
        value,
        source: project.source_language,
        target: project.target_language,
      });
    }
  }

  return [...seen.values()];
}

function subjectTitle(settings: WorkspaceSettings | undefined, subject: string | null): string | null {
  if (subject === null || settings === undefined) {
    return subject;
  }

  return settings.subjects.find((item) => item.id === subject)?.title ?? subject;
}
