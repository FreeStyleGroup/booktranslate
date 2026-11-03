import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { currentUser } from "../../../../../lib/current-user";
import { organizationId } from "../../../../../lib/session";
import {
  load,
  type BookRelease,
  type PageAudit,
  type ReleaseControl,
  type ReleaseFiles,
} from "../../../../../lib/work";
import "../../../../work.css";
import "../../../../ui/ui.css";
import "../../../books.css";
import "../../../../issues/issues.css";
import { CopyId } from "../../../../ui/copy-id";
import { paramsOf, wholeNumber } from "../../../../ui/query";
import { FilesPanel, GatePanel, PageAuditPanel } from "./release-desk";

export const metadata: Metadata = {
  title: "Контроль выпуска — BookTranslate",
  description: "Чек-лист выпуска, файлы DOCX и PDF, постраничный аудит и подтверждение выпуска.",
};

/* Контроль выпуска.

   Чек-лист тот же, по которому решает сервер: кнопка подтверждения зовёт ту же проверку. Страницы PDF
   приходят картинками с сервера, поэтому они видны в любом браузере, а стороннего просмотрщика нет.
   Номер страницы хранится в адресе: ссылка ведёт на ту самую страницу. */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const PAGE_MAX = 100_000;

// Те же наборы, что в API.
const PASSING = new Set(["owner", "admin", "manager"]);
const AUDITING = new Set(["owner", "admin", "manager", "reviewer"]);

export default async function ReleaseControlPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string; releaseId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id, releaseId } = await params;

  if (!UUID.test(id) || !UUID.test(releaseId)) {
    notFound();
  }

  const here = `/app/books/${id}/releases/${releaseId}`;
  const query = paramsOf(await searchParams);

  const [release, gate, files, me, organization] = await Promise.all([
    load<BookRelease>(`/book-releases/${releaseId}`, here),
    load<ReleaseControl>(`/releases/${releaseId}/gate`, here),
    load<ReleaseFiles>(`/book-releases/${releaseId}/artifacts`, here),
    currentUser(here),
    organizationId(),
  ]);

  if (release.error !== undefined || gate.error !== undefined) {
    return (
      <section className="tile">
        <h2>Контроль выпуска</h2>
        <p className="tile__empty">{release.error ?? gate.error}</p>
        <div className="tile__foot">
          <Link className="btn btn--ghost btn--small" href={`/app/books/${id}/assembly`}>
            К сборке книги
          </Link>
        </div>
      </section>
    );
  }

  if (release.data.book_id !== id) {
    notFound();
  }

  const membership =
    me?.memberships.find((item) => item.organization_id === organization) ?? me?.memberships[0];
  const role = membership?.role ?? "viewer";

  const pdf = files.data?.artifacts.find((item) => item.format === "pdf");
  const pages =
    pdf !== undefined ? await load<PageAudit[]>(`/artifacts/${pdf.id}/pages`, here) : undefined;
  const firstWaiting = pages?.data?.find((item) => item.status === "unreviewed")?.page_no ?? 1;
  const requested = query.get("page");
  const pageNo = requested === null ? firstWaiting : wholeNumber(requested, firstWaiting, PAGE_MAX);

  return (
    <>
      <header className="wk-head">
        <div>
          <p className="wk-crumbs">
            <Link href="/app/books">Книги</Link>
            <span aria-hidden="true"> · </span>
            <Link href={`/app/books/${id}`}>{release.data.title}</Link>
            <span aria-hidden="true"> · </span>
            <Link href={`/app/books/${id}/assembly`}>Сборка</Link>
          </p>
          <h1>Контроль выпуска</h1>
          <p className="tile__note">
            {release.data.chapters.map((row) => row.release_code).join(", ")}
          </p>
        </div>
        <div className="bk-head__side">
          <CopyId value={release.data.code} title="код выпуска" />
        </div>
      </header>

      <GatePanel
        bookId={id}
        release={release.data}
        gate={gate.data}
        canPass={PASSING.has(role)}
      />

      {files.data !== undefined && (
        <FilesPanel
          bookId={id}
          release={release.data}
          files={files.data}
          canRender={PASSING.has(role)}
        />
      )}

      {pdf !== undefined && pages?.data !== undefined && (
        <PageAuditPanel
          key={`${pdf.id}-${pageNo}`}
          bookId={id}
          releaseId={releaseId}
          artifact={pdf}
          pages={pages.data}
          pageNo={Math.min(Math.max(pageNo, 1), Math.max(pdf.page_count ?? 1, 1))}
          canAudit={AUDITING.has(role) && release.data.status !== "passed"}
          here={here}
        />
      )}
    </>
  );
}
