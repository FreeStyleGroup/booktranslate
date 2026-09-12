"use client";

/* Перевод книги: постановка в очередь и наблюдение за ней.

   Книга не переводится в браузере. Человек ставит её в очередь и уходит:
   работает отдельный процесс на сервере, а по готовности приходит
   уведомление. Закрытая вкладка, потерянная связь и выключённый ноутбук
   переводу больше не мешают — раньше мешали все три.

   Отсюда устройство экрана: кнопка не «перевести», а «поставить в
   очередь», и то, что показано после неё, — не ход работы этой страницы, а
   состояние задания на сервере. Страница его спрашивает раз в несколько
   секунд и ничего не делает сама.

   🔥 Остановка не отменяет сделанного. Переведённое записано после каждой
   пачки, и за него уже заплачено; отменяется только продолжение. Сказать
   это надо там же, где стоит кнопка, — иначе «остановить» читается как
   «отменить перевод». */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import type { TranslationJob } from "../../lib/work";
import { plural, thousands, when } from "../labels";
import { cancelJob, documentJob, queueDocument } from "../actions";

// Как часто спрашивать о ходе работы. Четыре секунды: пачка в сотню
// сегментов занимает у настоящей модели больше, и опрашивать чаще значит
// получать один и тот же ответ.
const POLL_MS = 4000;

/** Идёт ли работа по заданию. */
function live(job: TranslationJob | null): boolean {
  return job !== null && (job.state === "waiting" || job.state === "running");
}

/** Книга без терминологического прохода: что делать дальше.
 *
 * Два выхода, а не один. Проход — правильный путь, и он первый. Но
 * запретить перевод без него нельзя: у короткой книги на три страницы
 * терминология не окупается, и человек, которому надо просто посмотреть,
 * как оно работает, не должен упираться в стену. Цена решения написана
 * рядом, а не спрятана.
 */
export function BeforeTranslate({
  documentId,
  untranslated,
  job,
}: {
  documentId: string;
  untranslated: number;
  job: TranslationJob | null;
}) {
  const [skip, setSkip] = useState(false);

  // Книга уже в очереди — предлагать выбор поздно: работа идёт.
  if (skip || live(job)) {
    return <TranslateRun documentId={documentId} untranslated={untranslated} job={job} />;
  }

  return (
    <section className="tile wk-call">
      <h3>Следующий шаг — термины</h3>
      <p>
        Программа пройдёт по тексту и соберёт то, что в нём повторяется:
        термины, аббревиатуры, обозначения. Решается это один раз и до
        перевода, а дальше держит всю книгу и все следующие книги проекта.
      </p>
      <div className="tile__foot">
        <Link className="btn btn--primary btn--small" href={`/app/terms?document=${documentId}`}>
          Термины книги
        </Link>
        <button
          className="btn btn--ghost btn--small"
          type="button"
          onClick={() => setSkip(true)}
        >
          Перевести без словаря
        </button>
      </div>
      <p className="tile__note wk-seg__foot">
        Без словаря перевод тоже пойдёт, но каждое незнакомое слово модель
        решит сама и в разных местах по-разному. На короткой книге это
        терпимо, на руководстве в четыреста страниц — нет.
      </p>
    </section>
  );
}

export function TranslateRun({
  documentId,
  untranslated,
  job: initial,
}: {
  documentId: string;
  untranslated: number;
  job: TranslationJob | null;
}) {
  const router = useRouter();

  const [job, setJob] = useState<TranslationJob | null>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const working = live(job);

  const ask = useCallback(async () => {
    const answer = await documentJob(documentId);

    if (answer.error !== undefined || answer.job === undefined) {
      // Один неудачный опрос — не повод пугать человека: работа идёт на
      // сервере и от нашего вопроса не зависит. Следующий опрос через
      // четыре секунды.
      return;
    }

    setJob(answer.job);

    if (answer.job !== null && !live(answer.job)) {
      // Работа кончилась — странице пора перечитать паспорт книги: там
      // теперь и расход, и состояние сегментов.
      router.refresh();
    }
  }, [documentId, router]);

  /* Опрос, пока задание живо.
     Состояние меняется в обработчике таймера, а не в самом эффекте: эффект
     только заводит и снимает таймер. */
  useEffect(() => {
    if (!working) {
      return;
    }

    const timer = setInterval(() => {
      void ask();
    }, POLL_MS);

    return () => clearInterval(timer);
  }, [working, ask]);

  async function start(): Promise<void> {
    setBusy(true);
    setError(null);

    const answer = await queueDocument(documentId);

    setBusy(false);

    if (answer.error !== undefined || answer.job === undefined) {
      setError(answer.error ?? "Не удалось поставить книгу в очередь");
      return;
    }

    setJob(answer.job);
  }

  async function stop(): Promise<void> {
    if (job === null) {
      return;
    }

    setBusy(true);
    setError(null);

    const answer = await cancelJob(job.id, documentId);

    setBusy(false);

    if (answer.error !== undefined || answer.job === undefined) {
      setError(answer.error ?? "Не удалось остановить перевод");
      return;
    }

    setJob(answer.job);
    router.refresh();
  }

  return (
    <section className="tile wk-call">
      <h3>{working ? "Книга переводится" : "Перевод"}</h3>

      {job === null || job.state === "failed" || job.state === "cancelled" ? (
        <Idle job={job} untranslated={untranslated} />
      ) : (
        <Working job={job} />
      )}

      {error !== null && (
        <p className="form__error" role="alert">
          {error}
        </p>
      )}

      <div className="tile__foot">
        {working ? (
          <button
            className="btn btn--ghost btn--small"
            type="button"
            disabled={busy}
            onClick={() => void stop()}
          >
            {busy ? "Останавливаем…" : "Остановить"}
          </button>
        ) : (
          <button
            className="btn btn--primary btn--small"
            type="button"
            disabled={busy || untranslated === 0}
            onClick={() => void start()}
          >
            {busy ? "Ставим в очередь…" : job === null ? "Перевести книгу" : "Продолжить перевод"}
          </button>
        )}
      </div>

      {working && (
        <p className="tile__note wk-seg__foot">
          Страницу можно закрыть: книгу переводит сервер, а не она. По
          готовности придёт уведомление — если оно настроено в разделе
          «Настройки».
        </p>
      )}
    </section>
  );
}

/** Книга не в работе: объяснить, что будет, и чем кончилось прошлое. */
function Idle({ job, untranslated }: { job: TranslationJob | null; untranslated: number }) {
  return (
    <>
      {job?.state === "failed" && (
        <p className="form__error" role="alert">
          Прошлый перевод сорвался: {job.error ?? "причина не записана"}
        </p>
      )}

      {job?.state === "cancelled" && (
        <p className="wk-note" role="status">
          <span aria-hidden="true">✋</span> Перевод остановлен{" "}
          {when(job.finished_at ?? job.updated_at)} на {thousands(job.segments_done)}{" "}
          {plural(job.segments_done, "сегменте", "сегментах", "сегментах")}. Сделанное
          сохранено — продолжение начнётся с остатка.
        </p>
      )}

      <p>
        Книгу переведёт сервер, а не эта страница: {thousands(untranslated)}{" "}
        {plural(untranslated, "сегмент", "сегмента", "сегментов")} — это работа на минуты, а
        на большой книге на часы. Поставьте в очередь и закройте вкладку; по готовности
        придёт уведомление.
      </p>

      <p className="tile__note">
        Модель получит сегменты вместе с решёнными терминами и соседними
        абзацами — без них «он», «указанный выше» и опущенное подлежащее
        переводятся наугад. Повторы внутри книги и то, что уже есть в памяти
        переводов, в модель не уйдут вовсе.
      </p>
    </>
  );
}

/** Книга в работе: где она в очереди и сколько сделано. */
function Working({ job }: { job: TranslationJob }) {
  const percent =
    job.segments_total === 0
      ? 0
      : Math.min(100, Math.round((job.segments_done * 100) / job.segments_total));

  if (job.state === "waiting") {
    return (
      <>
        <p>
          Книга в очереди. Её возьмёт первый освободившийся рабочий — обычно
          это секунды.
        </p>
        {job.attempts > 0 && (
          <p className="tile__note">
            Заход {job.attempts}: прошлый оборвался, продолжение пойдёт с остатка.
          </p>
        )}
      </>
    );
  }

  return (
    <>
      <div className="tr-bar">
        <div className="bar">
          <i style={{ width: `${percent}%` }} />
        </div>
        <b>{percent}%</b>
      </div>

      <p className="tile__note">
        Переведено {thousands(job.segments_done)} из {thousands(job.segments_total)}{" "}
        {plural(job.segments_total, "сегмента", "сегментов", "сегментов")}
        {job.started_at !== null && ` · начали ${when(job.started_at)}`}
      </p>
    </>
  );
}
