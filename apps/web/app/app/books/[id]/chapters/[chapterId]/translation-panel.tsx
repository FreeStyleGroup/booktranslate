"use client";

/* Перевод главы: можно ли его начать, что идёт сейчас и чем кончился прошлый.

   Причины, которые держат главу, показываются до кнопки и теми же словами,
   что у API. Обход гейта — отдельная форма и только для тех, кому он разрешён:
   это решение с причиной, а не вторая кнопка рядом с первой.

   Пока прогон идёт, страница сама спрашивает, как дела: перевод главы — это
   минуты и часы, и обновлять вручную никто не должен. */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";

import type {
  ChapterEstimate,
  ChapterTranslation,
  TranslationRun,
} from "../../../../../lib/work";
import { JOB_LABEL, plural, thousands, when } from "../../../../labels";
import { ReportError, useToast } from "../../../../ui/toast";
import { cancelRun, startTranslation, type Result } from "../../../actions";

const POLL_MS = 4000;

function RunFacts({ run }: { run: TranslationRun }) {
  const tokens = run.input_tokens + run.output_tokens + run.cached_input_tokens;

  return (
    <dl className="bk-master__facts">
      <div>
        <dt>Модель</dt>
        <dd>{run.model}</dd>
      </div>
      <div>
        <dt>Версия промпта</dt>
        <dd>{run.prompt_version}</dd>
      </div>
      <div>
        <dt>Глоссарий</dt>
        <dd>{run.glossary_label ?? "без утверждённой версии"}</dd>
      </div>
      <div>
        <dt>Моделью</dt>
        <dd>{thousands(run.from_model)}</dd>
      </div>
      <div>
        <dt>Готовый перевод</dt>
        <dd>{thousands(run.from_memory)}</dd>
      </div>
      <div>
        <dt>Защищённых</dt>
        <dd>{thousands(run.copied)}</dd>
      </div>
      <div>
        <dt>Токенов</dt>
        <dd>{thousands(tokens)}</dd>
      </div>
      <div>
        <dt>Запущен</dt>
        <dd>{when(run.created_at)}</dd>
      </div>
    </dl>
  );
}

export function TranslationPanel({
  bookId,
  chapterId,
  state,
  estimate,
  canTranslate,
  canBypass,
}: {
  bookId: string;
  chapterId: string;
  state: ChapterTranslation;
  estimate: ChapterEstimate | null;
  canTranslate: boolean;
  canBypass: boolean;
}) {
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [pending, start] = useTransition();
  const router = useRouter();
  const toast = useToast();

  const here = `/app/books/${bookId}/chapters/${chapterId}`;
  const live = state.live;
  const latest = state.latest;
  const percent = state.total === 0 ? 0 : Math.round((state.translated * 100) / state.total);

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

      setAsking(false);
      toast.ok(done);
      router.refresh();
    });
  }

  return (
    <section className={state.open ? "tile bk-gate is-open" : "tile bk-gate"}>
      <div className="tile__head">
        <h3>Перевод главы</h3>
        {live !== null ? (
          <span className="chip chip--info">{JOB_LABEL[live.state ?? "waiting"]}</span>
        ) : state.total > 0 && state.pending === 0 ? (
          <span className="chip chip--ok">переведена</span>
        ) : (
          <span className={state.open ? "chip chip--ok" : "chip chip--danger"}>
            {state.open ? "можно переводить" : "перевод закрыт"}
          </span>
        )}
      </div>

      <div className="bar" role="img" aria-label={`Переведено ${percent}%`}>
        <i style={{ width: `${percent}%` }} />
      </div>
      <p className="tile__note">
        Переведено {thousands(state.translated)} из {thousands(state.total)}{" "}
        {plural(state.total, "блока", "блоков", "блоков")}
        {state.glossary_label !== null && ` · глоссарий ${state.glossary_label}`}
        {state.master_label !== null && ` · мастер ${state.master_label}`}
      </p>

      {live !== null && (
        <p className="tile__note">
          Обработано {thousands(live.blocks_done)} из {thousands(live.blocks_total)}. Можно закрыть
          вкладку: перевод идёт на сервере, готовое сохраняется после каждой пачки.
        </p>
      )}

      {estimate !== null && estimate.untranslated > 0 && live === null && (
        <p className="tile__note">
          Смета: к оплате {thousands(estimate.billable_texts)}{" "}
          {plural(estimate.billable_texts, "текст", "текста", "текстов")}
          {estimate.estimate !== null && estimate.estimate.usd !== null
            ? `, около $${estimate.estimate.usd.toFixed(2)}`
            : ""}
          {" · "}
          повторов {thousands(estimate.repeated)}, готовый перевод есть у{" "}
          {thousands(estimate.book_matches + estimate.memory_matches)}, защищённых{" "}
          {thousands(estimate.protected)}. Это оценка сверху, а не счёт.
        </p>
      )}

      {state.blockers.length > 0 && (
        <ul className="bk-gate__list">
          {state.blockers.map((item, index) => (
            <li key={`${item.code}-${index}`}>{item.message}</li>
          ))}
        </ul>
      )}

      {state.warnings.length > 0 && (
        <ul className="bk-gate__list bk-gate__list--warn">
          {state.warnings.map((item, index) => (
            <li key={`${item.code}-${index}`}>{item.message}</li>
          ))}
        </ul>
      )}

      {latest !== null && latest.state === "failed" && latest.error !== null && (
        <p className="bk-mismatch" role="status">
          <span aria-hidden="true">⚠</span>
          <span>Прошлый прогон сорвался: {latest.error}</span>
        </p>
      )}

      {latest !== null && latest.ignore_terminology && (
        <p className="bk-mismatch" role="status">
          <span aria-hidden="true">⚠</span>
          <span>
            Глава переводилась в обход гейта терминологии: {latest.bypass_reason}. Такие блоки
            подлежат повторной проверке перед выпуском.
          </span>
        </p>
      )}

      {latest !== null && latest.rejections.length > 0 && (
        <details className="bk-raw">
          <summary>
            Без перевода осталось: {thousands(latest.rejections.length)}{" "}
            {plural(latest.rejections.length, "блок", "блока", "блоков")}
          </summary>
          <ul className="bk-gate__list">
            {latest.rejections.map((item) => (
              <li key={item.block_id}>
                <Link href={`${here}/translation/${item.block_id}`}>{item.code}</Link> —{" "}
                {item.reason}
              </li>
            ))}
          </ul>
        </details>
      )}

      {latest !== null && (
        <>
          <p className="tile__note">
            Последний прогон: {latest.kind === "retranslate" ? "перевод заново" : "черновой перевод"}
          </p>
          <RunFacts run={latest} />
        </>
      )}

      <div className="wk-actions">
        {canTranslate && live === null && state.pending > 0 && (
          <button
            className="btn btn--primary"
            type="button"
            disabled={pending || !state.open}
            title={state.open ? undefined : "Сначала снимите причины выше"}
            onClick={() =>
              run(() => startTranslation(bookId, chapterId, null), "Глава поставлена в очередь")
            }
          >
            {state.translated > 0
              ? `Перевести остаток: ${thousands(state.pending)}`
              : "Перевести главу"}
          </button>
        )}

        {canTranslate && live !== null && live.job_id !== null && (
          <button
            className="btn btn--ghost"
            type="button"
            disabled={pending}
            onClick={() =>
              run(
                () => cancelRun(bookId, chapterId, live.job_id ?? ""),
                "Перевод остановлен: готовое сохранено",
              )
            }
          >
            Остановить
          </button>
        )}

        {state.translated > 0 && (
          <Link className="btn btn--ghost" href={`${here}/translation`}>
            Открыть перевод
          </Link>
        )}

        {canBypass && state.bypassable && live === null && state.pending > 0 && !asking && (
          <button
            className="btn btn--ghost"
            type="button"
            disabled={pending}
            onClick={() => setAsking(true)}
          >
            Перевести в обход гейта
          </button>
        )}
      </div>

      {asking && (
        <form
          className="bk-reason"
          onSubmit={(event) => {
            event.preventDefault();
            const reason = String(new FormData(event.currentTarget).get("reason") ?? "");
            run(
              () => startTranslation(bookId, chapterId, reason),
              "Глава поставлена в очередь в обход гейта",
            );
          }}
        >
          <label className="field">
            <span>Почему переводим без утверждённого глоссария</span>
            <textarea
              name="reason"
              required
              minLength={10}
              maxLength={1000}
              rows={3}
              placeholder="Пробная глава для заказчика: термины согласуем по её итогам"
              // Форма открыта нажатием — печатать человек собирался именно здесь.
              autoFocus
            />
            <small>
              Причина остаётся в журнале и в прогоне, а такие блоки подлежат повторной проверке
              перед выпуском.
            </small>
          </label>

          <div className="wk-actions">
            <button className="btn btn--primary" type="submit" disabled={pending}>
              {pending ? "Ставим в очередь…" : "Перевести в обход гейта"}
            </button>
            <button
              className="btn btn--ghost"
              type="button"
              disabled={pending}
              onClick={() => setAsking(false)}
            >
              Отмена
            </button>
          </div>
        </form>
      )}

      <ReportError error={error} />
    </section>
  );
}
