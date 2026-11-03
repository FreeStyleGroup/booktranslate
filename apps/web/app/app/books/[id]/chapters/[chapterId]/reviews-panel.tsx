"use client";

/* Редактура и сверка главы: три работы по порядку.

   Процент считается по нынешнему тексту, а не по тому, что когда-то отметили: новая редакция сама
   возвращает блок в очередь, и завершённая работа может показать меньше ста. Это не ошибка, а правда:
   работа была про другой текст. Литературная правка так и действует на техническую редактуру, а
   финальная сверка обязана быть про текст, который уходит в выпуск. */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import type { ChapterReviews, ReviewKind, ReviewRun } from "../../../../../lib/work";
import { REVIEW_KIND_LABEL, reviewPercent, thousands, when } from "../../../../labels";
import { ReportError } from "../../../../ui/toast";
import { startReview } from "../../../review-actions";

const ORDER: { kind: ReviewKind; field: keyof ChapterReviews; after: keyof ChapterReviews | null }[] =
  [
    { kind: "technical", field: "technical", after: null },
    { kind: "literary", field: "literary", after: "technical" },
    { kind: "final_compare", field: "final_compare", after: "literary" },
  ];

const NEEDED: Record<ReviewKind, string> = {
  technical: "",
  literary: "Идёт после технической редактуры.",
  final_compare: "Идёт после литературной редактуры.",
};

function Facts({ run }: { run: ReviewRun }) {
  return (
    <p className="tile__note">
      Сверено {thousands(run.blocks_done)} из {thousands(run.blocks_total)} блоков,{" "}
      {thousands(run.objects_done)} из {thousands(run.objects_total)} объектов
      {run.untranslated > 0 && ` · без перевода ${thousands(run.untranslated)}`}
      {run.completed_at !== null && ` · завершена ${when(run.completed_at)}`}
      {run.reviewer !== null && ` · ${run.reviewer}`}
    </p>
  );
}

export function ReviewsPanel({
  bookId,
  chapterId,
  state,
  canReview,
  canEditStyle,
}: {
  bookId: string;
  chapterId: string;
  state: ChapterReviews;
  canReview: boolean;
  canEditStyle: boolean;
}) {
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const router = useRouter();
  const chapter = `/app/books/${bookId}/chapters/${chapterId}`;

  function begin(kind: ReviewKind): void {
    setError(null);

    start(async () => {
      const result = await startReview(bookId, chapterId, kind);

      if (result.error !== undefined || result.id === undefined) {
        setError(result.error ?? "Сервис не ответил");
        return;
      }

      router.push(`${chapter}/review/${result.id}`);
    });
  }

  return (
    <section className="tile">
      <div className="tile__head">
        <h3>Редактура и сверка</h3>
      </div>

      <div className="bk-checks bk-checks--three">
        {ORDER.map(({ kind, field, after }) => {
          const run = state[field];
          const earlier = after === null ? null : state[after];
          const allowed = kind === "literary" ? canEditStyle : canReview;
          const reachable = after === null || earlier?.status === "completed";
          const percent = run === null ? 0 : reviewPercent(run);

          return (
            <div className="bk-check" key={kind}>
              <div className="bk-check__head">
                <b>{REVIEW_KIND_LABEL[kind]}</b>
                {run === null ? (
                  <span className="chip chip--info">не начата</span>
                ) : run.status === "open" ? (
                  <span className="chip chip--warn">идёт</span>
                ) : run.stale ? (
                  <span className="chip chip--warn">текст изменился</span>
                ) : (
                  <span className="chip chip--ok">завершена</span>
                )}
              </div>

              <div className="bar" role="img" aria-label={`Покрытие ${percent}%`}>
                <i style={{ width: `${percent}%` }} />
              </div>

              {run === null ? (
                <p className="tile__note">{reachable ? "Покрытие 0%." : NEEDED[kind]}</p>
              ) : (
                <>
                  <p className="tile__note">Покрытие {percent}%.</p>
                  <Facts run={run} />
                </>
              )}

              <div className="wk-actions">
                {run !== null && run.status === "open" ? (
                  <Link
                    className="btn btn--primary btn--small"
                    href={`${chapter}/review/${run.id}`}
                  >
                    {allowed ? "Продолжить" : "Посмотреть"}
                  </Link>
                ) : (
                  allowed &&
                  reachable && (
                    <button
                      className={
                        run === null || run.stale
                          ? "btn btn--primary btn--small"
                          : "btn btn--ghost btn--small"
                      }
                      type="button"
                      disabled={pending}
                      onClick={() => begin(kind)}
                    >
                      {run === null ? "Начать" : "Пройти заново"}
                    </button>
                  )
                )}
              </div>
            </div>
          );
        })}
      </div>

      <ReportError error={error} />
    </section>
  );
}
