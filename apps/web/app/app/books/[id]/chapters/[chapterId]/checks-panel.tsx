"use client";

/* Проверки главы: два независимых индикатора и запуск.

   «Формально проверено» и «смысловая сверка выполнена» — разные вещи, и одна не заменяет другую.
   Ни та ни другая не значит «готово»: отсутствие находок лишь говорит, что проверка ничего не
   нашла, и в финальный текст блок от этого не переходит.

   Прогон помнит сумму текста, который проверял. Если она разошлась с нынешней, это сказано прямо:
   проверка была про другой текст. */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";

import type { ChapterChecks, QARun } from "../../../../../lib/work";
import { plural, thousands, when } from "../../../../labels";
import { ReportError, useToast } from "../../../../ui/toast";
import { cancelRun, startChecks, type Result } from "../../../actions";

const POLL_MS = 3000;

const SCOPE_NOTE: Record<ChapterChecks["semantic_scope"], string> = {
  risky: "только рискованное: числа, формулы, таблицы, предупреждения, обязательные термины",
  all: "все блоки, кроме листингов",
};

function Indicator({
  title,
  done,
  total,
  run,
  current,
}: {
  title: string;
  done: number;
  total: number;
  run: QARun | null;
  current: string;
}) {
  const full = total > 0 && done === total;
  const stale = run !== null && run.revision_set_hash !== current;

  return (
    <div className="bk-check">
      <div className="bk-check__head">
        <b>{title}</b>
        <span className={full ? "chip chip--ok" : "chip chip--info"}>
          {thousands(done)} из {thousands(total)}
        </span>
      </div>

      {run === null ? (
        <p className="tile__note">Ещё не запускалась.</p>
      ) : (
        <p className="tile__note">
          {when(run.created_at)} · {thousands(run.findings_total)}{" "}
          {plural(run.findings_total, "находка", "находки", "находок")}, новых замечаний:{" "}
          {thousands(run.issues_created)}
          {run.model !== null && ` · ${run.model}`}
          {stale && " · текст изменился после этой проверки"}
        </p>
      )}

      {run !== null && run.state === "failed" && run.error !== null && (
        <p className="bk-mismatch" role="status">
          <span aria-hidden="true">⚠</span>
          <span>Прогон сорвался: {run.error}</span>
        </p>
      )}

      {run !== null && run.rejections.length > 0 && (
        <p className="tile__note">
          Модель не проверила {thousands(run.rejections.length)}{" "}
          {plural(run.rejections.length, "блок", "блока", "блоков")}: {run.rejections[0].reason}
        </p>
      )}
    </div>
  );
}

export function ChecksPanel({
  bookId,
  chapterId,
  state,
  canCheck,
  canReview,
}: {
  bookId: string;
  chapterId: string;
  state: ChapterChecks;
  canCheck: boolean;
  canReview: boolean;
}) {
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const router = useRouter();
  const toast = useToast();
  const live = state.live;

  useEffect(() => {
    if (live === null) {
      return;
    }

    const timer = window.setInterval(() => router.refresh(), POLL_MS);

    return () => window.clearInterval(timer);
  }, [live, router]);

  function run(action: () => Promise<Result>, done: string): void {
    setError(null);

    start(async () => {
      const result = await action();

      if (result.error !== undefined) {
        setError(result.error);
        return;
      }

      toast.ok(done);
      router.refresh();
    });
  }

  if (state.total === 0) {
    return null;
  }

  return (
    <section className="tile">
      <div className="tile__head">
        <h3>Проверки</h3>
        {live !== null ? (
          <span className="chip chip--info">идёт проверка</span>
        ) : (
          <Link className="tile__note" href={`/app/qa?chapter=${chapterId}`}>
            Все находки
          </Link>
        )}
      </div>

      <div className="bk-checks">
        <Indicator
          title="Формально проверено"
          done={state.formal}
          total={state.translated}
          run={state.latest_formal}
          current={state.revision_set_hash}
        />
        <Indicator
          title="Смысловая сверка"
          done={state.semantic}
          total={state.translated}
          run={state.latest_semantic}
          current={state.revision_set_hash}
        />
      </div>

      {state.translated < state.total && (
        <p className="tile__note">
          Без перевода: {thousands(state.total - state.translated)}{" "}
          {plural(state.total - state.translated, "блок", "блока", "блоков")}. Их проверять нечего.
        </p>
      )}

      {live !== null && (
        <p className="tile__note">
          Обработано {thousands(live.blocks_checked)} из {thousands(live.blocks_total)}. Можно
          закрыть вкладку: проверка идёт на сервере.
        </p>
      )}

      <p className="tile__note">
        Находка не меняет текст: она становится замечанием реестра, и решает человек. Смысловая
        сверка тратит токены модели и берёт {SCOPE_NOTE[state.semantic_scope]}; за текст, который
        уже видела, второй раз не платит.
      </p>

      <div className="wk-actions">
        {canCheck && live === null && state.translated > 0 && (
          <button
            className="btn btn--primary"
            type="button"
            disabled={pending}
            onClick={() =>
              run(
                () => startChecks(bookId, chapterId, "deterministic"),
                "Формальная проверка поставлена в очередь",
              )
            }
          >
            Проверить формально
          </button>
        )}

        {canReview && live === null && state.translated > 0 && (
          <button
            className="btn btn--ghost"
            type="button"
            disabled={pending}
            onClick={() =>
              run(
                () => startChecks(bookId, chapterId, "semantic"),
                "Смысловая сверка поставлена в очередь",
              )
            }
          >
            Запустить смысловую сверку
          </button>
        )}

        {canCheck && live !== null && live.job_id !== null && (
          <button
            className="btn btn--ghost"
            type="button"
            disabled={pending}
            onClick={() =>
              run(
                () => cancelRun(bookId, chapterId, live.job_id ?? ""),
                "Проверка остановлена: найденное сохранено",
              )
            }
          >
            Остановить
          </button>
        )}
      </div>

      <ReportError error={error} />
    </section>
  );
}
