"use client";

/* Колокольчик: что с книгами, поставленными в очередь.

   Человек ставит книгу в очередь и уходит на другую страницу кабинета —
   а то и на другую книгу. Письмо о готовности приходит не всем и не
   сразу, и без колокольчика узнать, что книга готова, можно только
   вернувшись на её карточку. Здесь — последние задания пространства:
   что переводится, что готово, что сорвалось.

   Уведомления не хранятся отдельной таблицей: задание и есть событие, и
   второй список «событий» разошёлся бы с первым при первом же сбое.
   Что человек уже видел, помнит его браузер — отметка времени последнего
   открытия. Это удобство одного устройства, а не общее состояние: на
   другом компьютере те же книги покажутся новыми ещё раз, и это лучше,
   чем не показать готовую книгу вовсе.

   Опрос идёт сам: раз в минуту, пока тихо, и раз в несколько секунд, пока
   что-то переводится, — по готовности число на значке меняется без
   перезагрузки страницы. */

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import type { TranslationJob } from "../lib/work";
import { recentJobs } from "./actions";
import { plural, thousands, when } from "./labels";

const SEEN_KEY = "bt-bell-seen";

// Пока ничего не переводится, спрашивать чаще незачем: новые задания
// появляются руками человека, и он сам знает, что поставил.
const IDLE_MS = 60_000;
const LIVE_MS = 6_000;

function live(job: TranslationJob): boolean {
  return job.state === "waiting" || job.state === "running";
}

/** Задание, о котором стоит сообщить: кончилось само, а не остановлено. */
function reportable(job: TranslationJob): boolean {
  return (
    job.finished_at !== null && (job.state === "done" || job.state === "failed")
  );
}

function finishedAfter(job: TranslationJob, since: number): boolean {
  return reportable(job) && Date.parse(job.finished_at ?? "") > since;
}

function readSeen(): number {
  try {
    return Number(window.localStorage.getItem(SEEN_KEY) ?? 0) || 0;
  } catch {
    return 0;
  }
}

function writeSeen(value: number): void {
  try {
    window.localStorage.setItem(SEEN_KEY, String(value));
  } catch {
    // Хранение запрещено — отметка не переживёт перезагрузку, и книги
    // покажутся новыми ещё раз. Это не поломка.
  }
}

export function Bell({ active }: { active: boolean }) {
  const [jobs, setJobs] = useState<TranslationJob[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);
  // На сервере хранилища нет, и отметка там нулевая; на клиенте она
  // настоящая. Разметка от этого не расходится: число на значке
  // считается по заданиям, а их при первой отрисовке ещё нет.
  const [seen, setSeen] = useState(readSeen);
  // С какого момента задания считаются новыми внутри открытого списка.
  // Отметка «видел» ставится при открытии, а подсветка должна остаться до
  // закрытия — иначе список открывается уже без единого нового.
  const [highlightSince, setHighlightSince] = useState(0);
  const root = useRef<HTMLDivElement>(null);

  const ask = useCallback(async () => {
    const answer = await recentJobs();

    if (answer.jobs === undefined) {
      // Один неудачный опрос — не повод менять значок: следующий через
      // минуту. Отказ показывается только в открытом списке.
      setFailed(true);
      return;
    }

    setFailed(false);
    setJobs(answer.jobs);
  }, []);

  const working = jobs !== null && jobs.some(live);

  /* Опрос: первый — сразу, дальше с шагом по тому, идёт ли работа.
     Состояние меняется в обработчике таймера, а не в самом эффекте: эффект
     только заводит и снимает таймер. Смена шага перезаводит цепочку — и
     заодно спрашивает ещё раз, что после перехода «переводится → готово»
     как раз кстати. */
  useEffect(() => {
    if (!active) {
      return;
    }

    let timer = 0;

    async function tick(): Promise<void> {
      await ask();
      timer = window.setTimeout(() => void tick(), working ? LIVE_MS : IDLE_MS);
    }

    timer = window.setTimeout(() => void tick(), 0);

    return () => window.clearTimeout(timer);
  }, [active, working, ask]);

  useEffect(() => {
    if (!open) {
      return;
    }

    function onKey(event: KeyboardEvent): void {
      if (event.key === "Escape") {
        setOpen(false);
      }
    }

    function onPointer(event: MouseEvent): void {
      if (
        root.current !== null &&
        !root.current.contains(event.target as Node)
      ) {
        setOpen(false);
      }
    }

    document.addEventListener("keydown", onKey);
    document.addEventListener("click", onPointer);

    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("click", onPointer);
    };
  }, [open]);

  function toggle(): void {
    if (open) {
      setOpen(false);
      return;
    }

    const now = Date.now();

    setHighlightSince(seen);
    setSeen(now);
    writeSeen(now);
    setOpen(true);
  }

  const unseen =
    jobs === null ? 0 : jobs.filter((job) => finishedAfter(job, seen)).length;

  const label =
    unseen > 0
      ? `Уведомления: ${unseen} ${plural(unseen, "новое", "новых", "новых")}`
      : working
        ? "Уведомления: книга переводится"
        : "Уведомления";

  return (
    <div className="cab__bell" ref={root}>
      <button
        className={working ? "cab__icon is-live" : "cab__icon"}
        type="button"
        aria-label={label}
        aria-expanded={open}
        disabled={!active}
        onClick={toggle}
      >
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path
            d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15L6 16Zm4 4h4"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.7"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        {unseen > 0 && (
          <span className="cab__badge">{unseen > 9 ? "9+" : unseen}</span>
        )}
      </button>

      {open && (
        <div className="bell" role="dialog" aria-label="Задания на перевод">
          <div className="bell__head">
            <h4>Перевод книг</h4>
            <span className="tile__note">
              {working ? "идёт работа" : "последние задания"}
            </span>
          </div>

          {failed && jobs === null ? (
            <p className="bell__empty">
              Не удалось узнать о заданиях. Попробуем ещё раз через минуту.
            </p>
          ) : jobs === null ? (
            <p className="bell__empty">Спрашиваем…</p>
          ) : jobs.length === 0 ? (
            <p className="bell__empty">
              Заданий пока нет. Книга ставится в очередь на своей карточке — и
              её ход будет виден здесь.
            </p>
          ) : (
            <ul className="bell__list">
              {jobs.map((job) => (
                <Item
                  key={job.id}
                  job={job}
                  fresh={finishedAfter(job, highlightSince)}
                  onGo={() => setOpen(false)}
                />
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/** Одно задание: книга, что с ней и когда. */
function Item({
  job,
  fresh,
  onGo,
}: {
  job: TranslationJob;
  fresh: boolean;
  onGo: () => void;
}) {
  const percent =
    job.segments_total === 0
      ? 0
      : Math.min(
          100,
          Math.round((job.segments_done * 100) / job.segments_total),
        );

  return (
    <li className={fresh ? "bell__item is-new" : "bell__item"}>
      <span
        className={`bell__mark bell__mark--${job.state}`}
        aria-hidden="true"
      />
      <div className="bell__text">
        <Link href={`/app/documents/${job.document_id}`} onClick={onGo}>
          {job.document_title}
        </Link>
        <span className="bell__line">{describe(job, percent)}</span>
      </div>
    </li>
  );
}

function describe(job: TranslationJob, percent: number): string {
  switch (job.state) {
    case "waiting":
      return job.attempts > 0
        ? `в очереди · заход ${job.attempts + 1}`
        : "в очереди";
    case "running":
      return `переводится · ${percent}% · ${thousands(job.segments_done)} из ${thousands(job.segments_total)}`;
    case "done":
      return `переведена · ${thousands(job.segments_done)} ${plural(job.segments_done, "сегмент", "сегмента", "сегментов")} · ${when(job.finished_at ?? job.updated_at)}`;
    case "failed":
      return `сорвалась · ${when(job.finished_at ?? job.updated_at)} · ${job.error ?? "причина не записана"}`;
    case "cancelled":
      return `остановлена · ${when(job.finished_at ?? job.updated_at)}`;
  }
}
