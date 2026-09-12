import type { Metadata } from "next";
import Link from "next/link";

import { currentUser } from "../../lib/current-user";
import { organizationId } from "../../lib/session";
import { load, type CatalogEntry, type CatalogSource, type Project } from "../../lib/work";
import { thousands } from "../labels";
import "../work.css";
import "./catalog.css";
import { EntryList } from "./entry-list";
import { LookupForm, type Pair } from "./lookup-form";

export const metadata: Metadata = {
  title: "Каталог справок — BookTranslate",
  description: "Что бюро уже выяснило про незнакомые слова — с источниками.",
};

/* Каталог справок рабочего пространства.

   Каталог — не словарь. Словарь хранит решения: как этот заказчик
   называет эту вещь. Каталог хранит справки: что такое slippage, откуда
   это известно и какой перевод предлагают источники. Справка не обязывает
   ни к чему; в словарь она попадает только решением человека — кнопкой.

   Незнакомое слово смотрят один раз: справка переживает книгу и достаётся
   следующей бесплатно. Ненайденное тоже помнится. */

const PAGE = 100;
const EDITING = new Set(["owner", "admin", "manager", "translator"]);

function parseOffset(value: string | undefined): number {
  const parsed = Number.parseInt(value ?? "", 10);

  return Number.isInteger(parsed) && parsed > 0 ? parsed : 0;
}

function pageHref(query: string, offset: number): string {
  const parameters = new URLSearchParams();

  if (query !== "") {
    parameters.set("query", query);
  }

  if (offset > 0) {
    parameters.set("offset", String(offset));
  }

  const suffix = parameters.toString();

  return suffix === "" ? "/app/catalog" : `/app/catalog?${suffix}`;
}

export default async function CatalogPage({
  searchParams,
}: {
  searchParams: Promise<{ query?: string; offset?: string }>;
}) {
  const { query = "", offset: offsetParam } = await searchParams;
  const offset = parseOffset(offsetParam);
  const here = pageHref(query, offset);

  const parameters = new URLSearchParams();
  parameters.set("limit", String(PAGE));
  parameters.set("offset", String(offset));

  if (query !== "") {
    parameters.set("query", query);
  }

  const [entries, source, projects, me, organization] = await Promise.all([
    load<CatalogEntry[]>(`/catalog?${parameters.toString()}`, here),
    load<CatalogSource>("/catalog/source", here),
    load<Project[]>("/projects?limit=200", here),
    currentUser(here),
    organizationId(),
  ]);

  if (entries.error !== undefined) {
    return (
      <section className="tile">
        <h2>Каталог справок</h2>
        <p className="tile__empty">{entries.error}</p>
      </section>
    );
  }

  const membership =
    me?.memberships.find((item) => item.organization_id === organization) ?? me?.memberships[0];
  const edits = membership !== undefined && EDITING.has(membership.role);
  const pairs = distinctPairs(projects.data ?? []);
  const filtered = query !== "";
  // Общего числа API не отдаёт: полная страница означает, что дальше
  // что-то есть — либо ровно ничего, и следующая страница будет пустой.
  const more = entries.data.length === PAGE;

  return (
    <>
      <header className="wk-head ct-head">
        <div>
          <h1>Каталог справок</h1>
          <p className="tile__note">
            Что бюро уже выяснило про незнакомые слова: определение, перевод по источникам, ссылки.
            Справка ничего не решает — в словарь она попадает только вашей кнопкой.
          </p>
        </div>
      </header>

      {edits &&
        (pairs.length === 0 ? (
          <section className="tile ct-block">
            <p className="tile__empty">
              Справка привязана к языковой паре, а пара задаётся проектом. Заведите проект — и здесь
              появится форма запроса.
            </p>
          </section>
        ) : (
          <LookupForm pairs={pairs} source={source.data ?? null} />
        ))}

      <section className="tile ct-block">
        <div className="tile__head">
          <h3>Справки</h3>
          <span className="tile__note">
            {filtered ? "по отбору" : "показано"} {thousands(entries.data.length)}
            {more && "+"}
          </span>
        </div>

        <form className="ct-filters" method="get">
          <input
            type="search"
            name="query"
            defaultValue={query}
            placeholder="Слово, перевод или кусок определения"
            aria-label="Поиск по каталогу"
          />
          <button className="btn btn--ghost btn--small" type="submit">
            Показать
          </button>
          {filtered && (
            <Link className="btn btn--ghost btn--small" href="/app/catalog">
              Сбросить
            </Link>
          )}
        </form>

        {entries.data.length === 0 ? (
          <p className="tile__empty">
            {filtered
              ? "По этому отбору ничего нет. Поиск идёт и по определению: попробуйте слово из смысла."
              : "Каталог пуст. Спросите про слова выше или запустите справки с экрана терминов книги — найденное останется здесь."}
          </p>
        ) : (
          <EntryList entries={entries.data} edits={edits} />
        )}

        {(offset > 0 || more) && (
          <nav className="ct-pager" aria-label="Страницы каталога">
            <span className="tile__note">
              Показаны {offset + 1}–{offset + entries.data.length}
            </span>
            <div className="wk-actions">
              {offset > 0 && (
                <Link
                  className="btn btn--ghost btn--small"
                  href={pageHref(query, Math.max(0, offset - PAGE))}
                >
                  ← Назад
                </Link>
              )}
              {more && (
                <Link className="btn btn--ghost btn--small" href={pageHref(query, offset + PAGE)}>
                  Дальше →
                </Link>
              )}
            </div>
          </nav>
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
