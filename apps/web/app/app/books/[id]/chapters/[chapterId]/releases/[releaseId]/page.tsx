import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { load, type ChapterRelease, type WorkingChange } from "../../../../../../../lib/work";
import { plural, shortHash, thousands } from "../../../../../../labels";
import "../../../../../../work.css";
import "../../../../../../ui/ui.css";
import "../../../../../books.css";
import { CopyId } from "../../../../../../ui/copy-id";
import { RevisionDiff } from "../../../../../revision-diff";

export const metadata: Metadata = {
  title: "Версия главы — BookTranslate",
  description: "Чем рабочий текст главы отличается от её финальной версии.",
};

/* Разница между рабочим текстом и финальной версией главы.

   Версия от этого не меняется: она закреплена манифестом. Страница отвечает на вопрос, стоит ли
   выпускать новую версию и что в неё войдёт. */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function ChapterReleasePage({
  params,
}: {
  params: Promise<{ id: string; chapterId: string; releaseId: string }>;
}) {
  const { id, chapterId, releaseId } = await params;

  if (![id, chapterId, releaseId].every((item) => UUID.test(item))) {
    notFound();
  }

  const chapterHref = `/app/books/${id}/chapters/${chapterId}`;
  const here = `${chapterHref}/releases/${releaseId}`;

  const [release, changes] = await Promise.all([
    load<ChapterRelease>(`/chapter-releases/${releaseId}`, here),
    load<WorkingChange[]>(`/chapter-releases/${releaseId}/changes`, here),
  ]);

  if (release.error !== undefined) {
    return (
      <section className="tile">
        <h2>Версия главы</h2>
        <p className="tile__empty">{release.error}</p>
        <div className="tile__foot">
          <Link className="btn btn--ghost btn--small" href={chapterHref}>
            К главе
          </Link>
        </div>
      </section>
    );
  }

  if (release.data.chapter_id !== chapterId || release.data.book_id !== id) {
    notFound();
  }

  const rows = changes.data ?? [];

  return (
    <>
      <header className="wk-head">
        <div>
          <p className="wk-crumbs">
            <Link href="/app/books">Книги</Link>
            <span aria-hidden="true"> · </span>
            <Link href={chapterHref}>Глава</Link>
          </p>
          <h1>Что изменилось с версии {release.data.version}</h1>
          <p className="tile__note">
            Сумма манифеста {shortHash(release.data.manifest_hash)}. Сама версия не меняется.
          </p>
        </div>
        <div className="bk-head__side">
          <CopyId value={release.data.code} title="код версии" />
        </div>
      </header>

      <section className="tile">
        <div className="tile__head">
          <h3>
            {rows.length === 0
              ? "Рабочий текст совпадает с этой версией"
              : `Отличается ${thousands(rows.length)} ${plural(rows.length, "блок", "блока", "блоков")}`}
          </h3>
        </div>

        {changes.error !== undefined && <p className="tile__empty">{changes.error}</p>}

        {rows.map((row) => (
          <div className="bk-review__context" key={row.block_id}>
            <p className="tile__note">
              <Link href={`${chapterHref}/translation/${row.block_id}`}>{row.code}</Link>
            </p>
            {row.final_text === null ? (
              <p className="tile__note">Этого блока в версии не было.</p>
            ) : row.working_text === null ? (
              <p className="tile__note">Этого блока больше нет в рабочем тексте.</p>
            ) : (
              <RevisionDiff items={row.changes} />
            )}
          </div>
        ))}
      </section>
    </>
  );
}
