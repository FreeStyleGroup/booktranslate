import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { load, type SearchResult } from "../../lib/work";
import { GLOSSARY_KIND, KIND_ONE, languagePair, plural, thousands } from "../labels";
import "../work.css";
import "./search.css";

export const metadata: Metadata = {
  title: "Поиск — BookTranslate",
  description: "Одно слово — везде, где оно может лежать.",
};

/* Результаты поиска из шапки.

   Человек не знает заранее, где лежит слово: в названии книги, в словаре,
   в справке или в тексте на странице сорок. Поэтому ищется везде, а
   группы идут по очереди — от короткого к длинному. В каждой показано
   несколько первых, а общее число ведёт в свой раздел с тем же отбором.

   Блок ведёт на свою страницу в переводе главы: там его история редакций. */

const MIN_QUERY = 2;

// Полный код блока или объекта: `BK01-CH03-B0042`, `BK01-CH03-FIG001`.
const FULL_CODE = /^BK\d+-CH\d+-(?:B|FIG|TBL|EQ|CODE)\d+$/i;
const SHOWN = 5;

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{ query?: string }>;
}) {
  const { query = "" } = await searchParams;
  const trimmed = query.trim();

  // Полный код — не слово для поиска, а адрес: такой блок или объект в
  // пространстве один, и показывать вместо него список совпадений незачем.
  if (FULL_CODE.test(trimmed)) {
    redirect(`/app/find?code=${encodeURIComponent(trimmed)}`);
  }
  const here = trimmed === "" ? "/app/search" : `/app/search?query=${encodeURIComponent(trimmed)}`;

  const result =
    trimmed.length >= MIN_QUERY
      ? await load<SearchResult>(
          `/search?query=${encodeURIComponent(trimmed)}&limit=${SHOWN}`,
          here,
        )
      : null;

  return (
    <>
      <header className="wk-head sr-head">
        <div>
          <h1>Поиск</h1>
          <p className="tile__note">
            Файлы, словарь, справки, текст книг и ошибки — по подстроке, без учёта регистра.
          </p>
        </div>
      </header>

      <form className="tile sr-form" action="/app/search" method="get" role="search">
        <input
          type="search"
          name="query"
          defaultValue={query}
          placeholder="Например: клапан, valve, ГОСТ"
          aria-label="Что искать"
          minLength={MIN_QUERY}
          maxLength={200}
          autoComplete="off"
          autoFocus
        />
        <button className="btn btn--primary" type="submit">
          Найти
        </button>
      </form>

      {result === null ? (
        trimmed !== "" && <p className="tile__note">Напишите хотя бы два знака.</p>
      ) : result.error !== undefined ? (
        <section className="tile">
          <p className="tile__empty">{result.error}</p>
        </section>
      ) : (
        <Results result={result.data} />
      )}
    </>
  );
}

function Results({ result }: { result: SearchResult }) {
  const { query, documents, terms, entries, blocks, issues } = result;
  const total = documents.total + terms.total + entries.total + blocks.total + issues.total;

  if (total === 0) {
    return (
      <section className="tile">
        <p className="tile__empty">
          По запросу «{query}» ничего нет — ни в книгах, ни в словаре, ни в справках, ни в тексте, ни в ошибках.
        </p>
      </section>
    );
  }

  const encoded = encodeURIComponent(query);

  return (
    <>
      <p className="tile__note sr-total">
        Найдено {thousands(total)} {plural(total, "совпадение", "совпадения", "совпадений")} по
        запросу «{query}».
      </p>

      {documents.total > 0 && (
        <Group
          title="Исходные файлы"
          total={documents.total}
          shown={documents.items.length}
          more="/app/documents"
        >
          {documents.items.map((item) => (
            <Link
              className="sr-row"
              key={item.id}
              href={item.book_id === null ? "/app/documents" : `/app/books/${item.book_id}`}
            >
              <span className="sr-row__main">
                <b>
                  <Mark text={item.title} query={query} />
                </b>
                <span className="tile__note">{item.original_filename ?? item.source_format}</span>
              </span>
            </Link>
          ))}
        </Group>
      )}

      {terms.total > 0 && (
        <Group
          title="Словарь"
          total={terms.total}
          shown={terms.items.length}
          more={`/app/glossary?query=${encoded}`}
        >
          {terms.items.map((item) => (
            <Link className="sr-row" key={item.id} href={`/app/glossary?query=${encoded}`}>
              <span className="sr-row__main">
                <b>
                  <Mark text={item.source_term} query={query} />
                  <span aria-hidden="true"> → </span>
                  <Mark text={item.target_term} query={query} />
                </b>
                <span className="tile__note">
                  {languagePair(item.source_language, item.target_language)} ·{" "}
                  {GLOSSARY_KIND[item.kind]}
                </span>
              </span>
            </Link>
          ))}
        </Group>
      )}

      {entries.total > 0 && (
        <Group
          title="Каталог справок"
          total={entries.total}
          shown={entries.items.length}
          more={`/app/catalog?query=${encoded}`}
        >
          {entries.items.map((item) => (
            <Link className="sr-row" key={item.id} href={`/app/catalog?query=${encoded}`}>
              <span className="sr-row__main">
                <b>
                  <Mark text={item.source_term} query={query} />
                  {item.suggested_target !== null && (
                    <>
                      <span aria-hidden="true"> → </span>
                      <Mark text={item.suggested_target} query={query} />
                    </>
                  )}
                </b>
                {item.definition !== null && item.definition !== "" && (
                  <span className="sr-row__text">
                    <Mark text={item.definition} query={query} />
                  </span>
                )}
              </span>
              {!item.found && <span className="chip chip--warn">не нашлось</span>}
            </Link>
          ))}
        </Group>
      )}

      {issues.total > 0 && (
        <Group title="Ошибки" total={issues.total} shown={issues.items.length} more="/app/issues">
          {issues.items.map((item) => (
            <Link className="sr-row" key={item.id} href={`/app/issues/${item.id}`}>
              <span className="sr-row__main">
                <b>
                  <Mark text={item.code} query={query} />
                </b>
                <span className="sr-row__text">
                  <Mark text={item.description} query={query} />
                </span>
              </span>
            </Link>
          ))}
        </Group>
      )}

      {blocks.total > 0 && (
        <Group title="Текст книг" total={blocks.total} shown={blocks.items.length} more={null}>
          {blocks.items.map((item) => (
            <Link
              className="sr-row"
              key={item.id}
              href={`/app/books/${item.book_id}/chapters/${item.chapter_id}/translation/${item.id}`}
            >
              <span className="sr-row__main">
                <span className="tile__note">
                  {item.book_title} · {item.full_code} · {KIND_ONE[item.kind] ?? item.kind}
                </span>
                <span className="sr-row__text">
                  <Mark text={item.source_text} query={query} />
                </span>
                {item.translation !== null && item.translation !== "" && (
                  <span className="sr-row__text sr-row__text--target">
                    <Mark text={item.translation} query={query} />
                  </span>
                )}
              </span>
            </Link>
          ))}
        </Group>
      )}
    </>
  );
}

function Group({
  title,
  total,
  shown,
  more,
  children,
}: {
  title: string;
  total: number;
  shown: number;
  // Куда идти за остальными; пусто — своего раздела с отбором нет.
  more: string | null;
  children: ReactNode;
}) {
  return (
    <section className="tile sr-group">
      <div className="tile__head">
        <h3>{title}</h3>
        <span className="tile__note">
          {shown < total ? `показано ${shown} из ${thousands(total)}` : thousands(total)}
        </span>
      </div>
      <div className="sr-list">{children}</div>
      {shown < total && more !== null && (
        <p className="sr-more">
          <Link className="btn btn--ghost btn--small" href={more}>
            Все {thousands(total)} в разделе →
          </Link>
        </p>
      )}
      {shown < total && more === null && (
        <p className="tile__note sr-more">
          Уточните запрос: остальные совпадения здесь не показаны.
        </p>
      )}
    </section>
  );
}

/** Подсветить совпадение в тексте. Длинный текст обрезается вокруг него:
 *  абзац на тысячу знаков в выдаче никто не читает. */
function Mark({ text, query }: { text: string; query: string }) {
  const window = 140;
  const lower = text.toLowerCase();
  const at = lower.indexOf(query.toLowerCase());

  if (at === -1) {
    return <>{text.length > window * 2 ? `${text.slice(0, window * 2)}…` : text}</>;
  }

  const start = Math.max(0, at - window);
  const end = Math.min(text.length, at + query.length + window);

  return (
    <>
      {start > 0 && "…"}
      {text.slice(start, at)}
      <mark>{text.slice(at, at + query.length)}</mark>
      {text.slice(at + query.length, end)}
      {end < text.length && "…"}
    </>
  );
}
