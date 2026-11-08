"use client";

/* Автоматический режим: одна кнопка и честное состояние.

   Видно, где книга сейчас и что её держит. Если сервис не может решить уверенно, он останавливается, и
   каждая причина ведёт туда, где её снимают. Готовый выпуск прямо говорит, что глазами его никто не
   смотрел: автомат не выдаёт себя за редактора. */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";

import type { AutopilotRun } from "../../../lib/work";
import { thousands, when } from "../../labels";
import { ReportError, useToast } from "../../ui/toast";
import {
  cancelAutopilot,
  resumeAutopilot,
  startAutopilot,
  type AutopilotResult,
} from "../autopilot-actions";

const POLL_MS = 5000;

export function AutopilotPanel({
  bookId,
  run,
  canRun,
}: {
  bookId: string;
  run: AutopilotRun | null;
  canRun: boolean;
}) {
  const [semantic, setSemantic] = useState(true);
  const [budget, setBudget] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const router = useRouter();
  const toast = useToast();

  const running = run?.status === "running";

  useEffect(() => {
    if (!running) {
      return;
    }

    const timer = window.setInterval(() => router.refresh(), POLL_MS);

    return () => window.clearInterval(timer);
  }, [running, router]);

  function act(action: () => Promise<AutopilotResult>, done: string): void {
    setError(null);

    start(async () => {
      const result = await action();

      if (result.error !== undefined) {
        setError(result.error);
        router.refresh();
        return;
      }

      toast.ok(done);
      router.refresh();
    });
  }

  const fresh = run === null || run.status === "cancelled";

  return (
    <section className={run?.status === "done" ? "tile bk-gate is-open" : "tile"}>
      <div className="tile__head">
        <h3>Автоматический режим</h3>
        {run !== null && (
          <span
            className={
              run.status === "done"
                ? "chip chip--ok"
                : run.status === "waiting_human"
                  ? "chip chip--danger"
                  : "chip chip--info"
            }
          >
            {
              {
                running: "идёт",
                waiting_human: "ждёт человека",
                done: "готово",
                cancelled: "остановлен",
              }[run.status]
            }
          </span>
        )}
      </div>

      {fresh && (
        <>
          <p className="tile__note">
            Сервис сам проведёт книгу через весь конвейер: главы, термины, перевод, проверки, рисунки,
            выпуск, DOCX и PDF. Замечания проверок он решает сам: исправляет перевод или объясняет,
            почему это не ошибка, — каждое решение видно в реестре и журнале. Остановится он только на
            том, что решить не смог, и покажет это сразу по всей книге.
          </p>

          {canRun && (
            <div className="is-form">
              <label className="bk-check-inline">
                <input
                  type="checkbox"
                  checked={semantic}
                  disabled={pending}
                  onChange={(event) => setSemantic(event.target.checked)}
                />
                <span>Смысловая сверка моделью: точнее, но расходует токены</span>
              </label>

              <label className="field">
                <span>Предел сметы перевода, долларов</span>
                <input
                  type="text"
                  inputMode="decimal"
                  value={budget}
                  disabled={pending}
                  placeholder="Без предела"
                  onChange={(event) => setBudget(event.target.value)}
                />
                <small>Если смета больше, сервис остановится до первого платного запроса.</small>
              </label>

              <div className="wk-actions">
                <button
                  className="btn btn--primary"
                  type="button"
                  disabled={pending}
                  onClick={() =>
                    act(
                      () => startAutopilot(bookId, semantic, budget),
                      "Автоматический режим запущен",
                    )
                  }
                >
                  {pending ? "Запускаем…" : "Перевести книгу автоматически"}
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {run !== null && run.status !== "cancelled" && (
        <>
          <ol className="bk-stages">
            {run.stages.map((stage) => (
              <li
                key={stage.code}
                className={`is-${stage.state}`}
                aria-current={stage.state === "current" ? "step" : undefined}
              >
                <span aria-hidden="true">
                  {stage.state === "done" ? "✓" : stage.state === "current" ? "●" : "○"}
                </span>
                <span>{stage.title}</span>
              </li>
            ))}
          </ol>

          <p className="tile__note">
            Глав с готовой версией: {thousands(run.chapters_done)} из {thousands(run.chapters_total)} ·
            запущен {when(run.created_at)}
            {run.finished_at !== null && ` · закончен ${when(run.finished_at)}`}
          </p>
        </>
      )}

      {run?.status === "waiting_human" && (
        <>
          <p className="bk-mismatch" role="status">
            <span aria-hidden="true">⚠</span>
            <span>Сервис остановился: это решает человек.</span>
          </p>

          {run.waiting.some((item) => item.issue_id !== null) && (
            <p className="tile__note">
              Эти замечания модель не смогла ни исправить, ни обосновать. Откройте каждое: ложную
              тревогу отклоните, ошибку подтвердите, исправьте и закройте. Потом нажмите
              «Решено, продолжить».
            </p>
          )}

          <ul className="bk-gate__list">
            {run.waiting.map((item, index) => (
              <li key={`${item.code}-${index}`}>
                {item.issue_id !== null ? (
                  <Link className="wk-link" href={`/app/issues/${item.issue_id}`}>
                    {item.message}
                  </Link>
                ) : item.figures && item.chapter_id !== null ? (
                  <Link
                    className="wk-link"
                    href={`/app/books/${bookId}/chapters/${item.chapter_id}/figures`}
                  >
                    {item.message}
                  </Link>
                ) : item.release_id !== null ? (
                  <Link className="wk-link" href={`/app/books/${bookId}/releases/${item.release_id}`}>
                    {item.message}
                  </Link>
                ) : item.chapter_id !== null ? (
                  <Link className="wk-link" href={`/app/books/${bookId}/chapters/${item.chapter_id}`}>
                    {item.message}
                  </Link>
                ) : (
                  item.message
                )}
              </li>
            ))}
          </ul>

          {canRun && (
            <div className="is-form">
              {run.waiting.some((item) => item.code === "over_budget") && (
                <label className="field">
                  <span>Новый предел сметы, долларов</span>
                  <input
                    type="text"
                    inputMode="decimal"
                    value={budget}
                    disabled={pending}
                    onChange={(event) => setBudget(event.target.value)}
                  />
                </label>
              )}

              <div className="wk-actions">
                <button
                  className="btn btn--primary"
                  type="button"
                  disabled={pending}
                  onClick={() =>
                    act(() => resumeAutopilot(bookId, run.id, budget), "Продолжаем")
                  }
                >
                  Решено, продолжить
                </button>
                <button
                  className="btn btn--ghost"
                  type="button"
                  disabled={pending}
                  onClick={() =>
                    act(() => cancelAutopilot(bookId, run.id), "Автоматический режим остановлен")
                  }
                >
                  Остановить
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {run?.status === "done" && run.release_id !== null && (
        <>
          <p className="tile__note">
            Выпуск собран и подтверждён автоматически: сервис проверил всё, что можно проверить без
            человека, но глазами текст и вёрстку никто не смотрел.
          </p>
          <div className="wk-actions">
            <Link
              className="btn btn--primary"
              href={`/app/books/${bookId}/releases/${run.release_id}`}
            >
              Открыть выпуск и файлы
            </Link>
          </div>
        </>
      )}

      {canRun && running && run !== null && (
        <div className="wk-actions">
          <button
            className="btn btn--ghost"
            type="button"
            disabled={pending}
            onClick={() => act(() => cancelAutopilot(bookId, run.id), "Автоматический режим остановлен")}
          >
            Остановить
          </button>
        </div>
      )}

      <ReportError error={error} />
    </section>
  );
}
