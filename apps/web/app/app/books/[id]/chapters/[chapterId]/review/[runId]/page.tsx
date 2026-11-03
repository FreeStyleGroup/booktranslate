import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { currentUser } from "../../../../../../../lib/current-user";
import { organizationId } from "../../../../../../../lib/session";
import {
  load,
  type ReviewNext,
  type ReviewRun,
} from "../../../../../../../lib/work";
import {
  REVIEW_KIND_LABEL,
  reviewPercent,
  thousands,
  when,
} from "../../../../../../labels";
import "../../../../../../work.css";
import "../../../../../../ui/ui.css";
import "../../../../../books.css";
import "../../../../../../issues/issues.css";
import { paramsOf, wholeNumber } from "../../../../../../ui/query";
import { BlockDesk, FinishDesk, ObjectDesk } from "./review-desk";

export const metadata: Metadata = {
  title: "Редактура главы — BookTranslate",
  description: "Последовательная сверка блоков и объектов главы с оригиналом.",
};

/* Режим редактуры: одно место за раз.

   Оригинал рядом с переводом, вокруг — термины, объекты и соседние блоки. Отметка ставится по одному
   месту и называет редакцию, которую человек видел. Пропустить можно: пропущенное вернётся в очередь,
   когда она дойдёт до конца. Куда продолжать, хранится в адресе, поэтому страницу можно открыть
   заново на том же месте. */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const POSITION_MAX = 1_000_000;

// Те же наборы, что в API: литературную правку вносит и переводчик, защищённое стережёт сервер.
const REVIEWING = new Set(["owner", "admin", "manager", "reviewer"]);
const EDITING_STYLE = new Set(["owner", "admin", "manager", "reviewer", "translator"]);

function position(value: string | null): number {
  return value === null ? -1 : wholeNumber(value, -1, POSITION_MAX);
}

export default async function ReviewPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string; chapterId: string; runId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id, chapterId, runId } = await params;

  if (!UUID.test(id) || !UUID.test(chapterId) || !UUID.test(runId)) {
    notFound();
  }

  const query = paramsOf(await searchParams);
  const after = position(query.get("after"));
  const afterObject = position(query.get("after_object"));
  const chapterHref = `/app/books/${id}/chapters/${chapterId}`;
  const here = `${chapterHref}/review/${runId}`;

  // Редактор проходит сотни мест подряд, и каждое — это загрузка страницы: запросов здесь минимум.
  const [run, next, me, organization] = await Promise.all([
    load<ReviewRun>(`/review-runs/${runId}`, here),
    load<ReviewNext>(`/review-runs/${runId}/next?after=${after}&after_object=${afterObject}`, here),
    currentUser(here),
    organizationId(),
  ]);

  if (run.error !== undefined) {
    return (
      <section className="tile">
        <h2>Редактура</h2>
        <p className="tile__empty">{run.error}</p>
        <div className="tile__foot">
          <Link className="btn btn--ghost btn--small" href={chapterHref}>
            К главе
          </Link>
        </div>
      </section>
    );
  }

  // Адрес собран из частей: работа другой главы здесь открываться не должна.
  if (run.data.chapter_id !== chapterId || run.data.book_id !== id) {
    notFound();
  }

  const membership =
    me?.memberships.find((item) => item.organization_id === organization) ?? me?.memberships[0];
  const role = membership?.role ?? "viewer";
  const canMark =
    run.data.status === "open" &&
    (run.data.kind === "literary" ? EDITING_STYLE.has(role) : REVIEWING.has(role));

  const percent = reviewPercent(run.data);
  const item = run.data.status === "open" ? next.data : undefined;

  return (
    <>
      <header className="wk-head">
        <div>
          <p className="wk-crumbs">
            <Link href="/app/books">Книги</Link>
            <span aria-hidden="true"> · </span>
            <Link href={`/app/books/${id}`}>{run.data.book_title}</Link>
            <span aria-hidden="true"> · </span>
            <Link href={chapterHref}>{run.data.chapter_title ?? "Глава"}</Link>
          </p>

          <h1>{REVIEW_KIND_LABEL[run.data.kind]}</h1>

          <p className="tile__note">
            Сверено {thousands(run.data.blocks_done)}/{thousands(run.data.blocks_total)} блоков,{" "}
            {thousands(run.data.objects_done)}/{thousands(run.data.objects_total)} объектов
            {run.data.reviewer !== null && ` · ${run.data.reviewer}`}
            {` · ${when(run.data.created_at)}`}
          </p>
        </div>

        <div className="bk-head__side">
          <span className={percent === 100 ? "chip chip--ok" : "chip chip--info"}>{percent}%</span>
        </div>
      </header>

      <div className="bar" role="img" aria-label={`Покрытие ${percent}%`}>
        <i style={{ width: `${percent}%` }} />
      </div>

      {run.data.status === "completed" && (
        <section className="tile">
          <div className="tile__head">
            <h3>Работа завершена</h3>
            <span className={run.data.stale ? "chip chip--warn" : "chip chip--ok"}>
              {run.data.stale ? "текст изменился" : "актуальна"}
            </span>
          </div>
          <p className="tile__note">
            {run.data.completed_at !== null && `Завершена ${when(run.data.completed_at)}. `}
            {run.data.stale
              ? "После этого текст главы менялся: работа была про другой текст, её можно пройти заново с экрана главы."
              : "Текст с тех пор не менялся."}
          </p>
          <div className="wk-actions">
            <Link className="btn btn--ghost" href={chapterHref}>
              К главе
            </Link>
          </div>
        </section>
      )}

      {item !== undefined && item.block !== null && (
        <BlockDesk
          key={item.block.revision_id}
          bookId={id}
          chapterId={chapterId}
          run={run.data}
          block={item.block}
          canMark={canMark}
          here={here}
        />
      )}

      {item !== undefined && item.block === null && item.object !== null && (
        <ObjectDesk
          key={item.object.content_hash}
          bookId={id}
          chapterId={chapterId}
          run={run.data}
          item={item.object}
          canMark={canMark}
          here={here}
        />
      )}

      {item !== undefined && item.block === null && item.object === null && (
        <FinishDesk
          bookId={id}
          chapterId={chapterId}
          run={run.data}
          canMark={canMark}
          chapterHref={chapterHref}
        />
      )}

      {next.error !== undefined && run.data.status === "open" && (
        <section className="tile">
          <p className="tile__empty">{next.error}</p>
        </section>
      )}
    </>
  );
}
