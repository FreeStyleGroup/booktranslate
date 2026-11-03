import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { currentUser } from "../../../../lib/current-user";
import { organizationId } from "../../../../lib/session";
import {
  load,
  type Assembly,
  type Book,
  type BookKit,
  type BookRelease,
} from "../../../../lib/work";
import { shortHash, thousands, when } from "../../../labels";
import "../../../work.css";
import "../../../ui/ui.css";
import "../../books.css";
import { CopyId } from "../../../ui/copy-id";
import { ExportLinks } from "../../export-links";
import { AssemblyForm } from "./assembly-form";

export const metadata: Metadata = {
  title: "Сборка книги — BookTranslate",
  description: "Состав выпуска: какие версии глав войдут и что мешает собрать книгу.",
};

/* Сборка книги.

   «Последняя утверждённая версия» здесь только подсказка: в выпуск записывается то, что выбрано, и
   выбор виден на экране. Выбор хранится в адресе: страницу можно открыть заново с тем же составом, а
   расхождения считает сервер под этот самый состав. */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Те же наборы, что в API.
const BUILDING = new Set(["owner", "admin", "manager"]);

export default async function AssemblyPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id } = await params;

  if (!UUID.test(id)) {
    notFound();
  }

  const wanted = (await searchParams).chosen;
  const chosen = (Array.isArray(wanted) ? wanted : wanted === undefined ? [] : [wanted]).filter(
    (item) => UUID.test(item),
  );
  const here = `/app/books/${id}/assembly`;
  const query = chosen.map((item) => `chapter_release_id=${item}`).join("&");

  const [book, plan, releases, kit, me, organization] = await Promise.all([
    load<Book>(`/books/${id}`, here),
    load<Assembly>(`/books/${id}/assembly${query === "" ? "" : `?${query}`}`, here),
    load<BookRelease[]>(`/books/${id}/releases`, here),
    load<BookKit>(`/books/${id}/sources`, here),
    currentUser(here),
    organizationId(),
  ]);

  if (book.error !== undefined || plan.error !== undefined) {
    return (
      <section className="tile">
        <h2>Сборка книги</h2>
        <p className="tile__empty">{book.error ?? plan.error}</p>
        <div className="tile__foot">
          <Link className="btn btn--ghost btn--small" href={`/app/books/${id}`}>
            К книге
          </Link>
        </div>
      </section>
    );
  }

  const membership =
    me?.memberships.find((item) => item.organization_id === organization) ?? me?.memberships[0];
  const canBuild = membership !== undefined && BUILDING.has(membership.role);

  return (
    <>
      <header className="wk-head">
        <div>
          <p className="wk-crumbs">
            <Link href="/app/books">Книги</Link>
            <span aria-hidden="true"> · </span>
            <Link href={`/app/books/${id}`}>{book.data.title}</Link>
          </p>
          <h1>Сборка книги</h1>
          <p className="tile__note">
            Выпуск называет версии глав явно: его состав не меняется, что бы ни происходило с рабочим
            текстом.
          </p>
        </div>
      </header>

      <AssemblyForm bookId={id} plan={plan.data} canBuild={canBuild} here={here} />

      {plan.data.toc.length > 0 && (
        <details className="tile bk-raw">
          <summary>Оглавление этого состава: {thousands(plan.data.toc.length)}</summary>
          <ul className="bk-review__list bk-toc">
            {plan.data.toc.map((entry, index) => (
              <li key={`${entry.chapter_code}-${index}`} data-level={entry.level}>
                {entry.text}
              </li>
            ))}
          </ul>
        </details>
      )}

      <section className="tile">
        <div className="tile__head">
          <h3>Выпуски</h3>
        </div>

        {(releases.data ?? []).length === 0 ? (
          <p className="tile__empty">Выпусков ещё нет.</p>
        ) : (
          <ul className="bk-releases">
            {(releases.data ?? []).map((item) => (
              <li key={item.id}>
                <div className="bk-releases__head">
                  <CopyId value={item.code} title="код выпуска" />
                  <span className={item.status === "passed" ? "chip chip--ok" : "chip chip--info"}>
                    {item.status === "passed" ? "контроль пройден" : "собран"}
                  </span>
                </div>
                <p className="tile__note">
                  {item.chapters.map((row) => row.release_code).join(", ")} · сумма{" "}
                  {shortHash(item.manifest_hash)} · {when(item.created_at)}
                </p>
                <div className="wk-actions">
                  <Link
                    className="btn btn--primary btn--small"
                    href={`/app/books/${id}/releases/${item.id}`}
                  >
                    Контроль выпуска
                  </Link>
                </div>
                <ExportLinks
                  path={`/api/book-releases/${item.id}/export`}
                  formats={kit.data?.export_formats ?? ["docx", "markdown", "text"]}
                  draft={false}
                />
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
