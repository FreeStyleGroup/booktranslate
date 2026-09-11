"use client";

/* Разбор кандидатов в словарь.

   Главная мысль экрана: решение по термину принимается глазами по
   контексту, а не по списку слов. `head` — это и «головка», и «оголовок», и
   различает их только кусок текста вокруг первого вхождения. Поэтому
   пример показан у каждой строки, а не спрятан за раскрытием.

   Решения копятся на странице и уходят одной пачкой. Так задумано: двести
   кандидатов — это одна работа человека, и отправлять по запросу на строку
   значит получить наполовину решённый словарь, если связь оборвётся
   посередине. Плюс так можно передумать, не заводя термин в словарь и не
   удаляя его оттуда.

   Работа не теряется при уходе со страницы: набранное лежит в localStorage
   до записи. Двести терминов не разбирают за один присест, а закрытая
   вкладка не должна стоить часа работы. */

import { useEffect, useMemo, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import { GLOSSARY_KIND, GLOSSARY_KIND_HINT, plural, thousands } from "../labels";
import { decideTerms, type Decision, type Report } from "./actions";

export type Candidate = {
  id: string;
  source_term: string;
  kind: string;
  status: string;
  frequency: number;
  sample: string;
  first_position: number;
  expansion: string | null;
};

/** Что человек решил по строке: пусто — ещё не решил. */
type Draft = { target: string; kind: string; reject: boolean };

const KINDS = Object.keys(GLOSSARY_KIND);

export function TermsBoard({
  documentId,
  candidates,
}: {
  documentId: string;
  candidates: Candidate[];
}) {
  const router = useRouter();
  const storageKey = `bt-terms-${documentId}`;

  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [busy, start] = useTransition();
  // Трогал ли человек хоть что-нибудь. Ссылкой, а не состоянием: от неё
  // ничего не перерисовывается, она только отличает «ещё не работали» от
  // «решения отменены до единого».
  const touched = useRef(false);

  /* Черновики читаются один раз, после подключения к разметке.

     Правило «не писать состояние из эффекта» тут нарушается осознанно, и
     другого места для этого чтения нет: страницу собирает сервер, где
     localStorage не существует вовсе, а прочитать его при первой
     отрисовке — значит разойтись с серверной разметкой ровно в тех полях,
     ради которых всё и делается. Круг отрисовки здесь один и на открытии
     страницы. */
  useEffect(() => {
    try {
      const saved = localStorage.getItem(storageKey);

      if (saved !== null) {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setDrafts(JSON.parse(saved) as Record<string, Draft>);
      }
    } catch {
      // Приватное окно, запрет на данные сайта, испорченная запись — всё
      // это значит «черновиков нет», а не «страница сломана».
    }
  }, [storageKey]);

  /* Черновики сохраняются отдельно от изменения состояния.

     🔥 Иначе выходит так: обработчик берёт прежние решения из своего
     замыкания, и два нажатия подряд — до того, как страница перерисуется, —
     затирают друг друга. На «не термин», проставленном по десятку строк
     быстрым перебором, записывалось одно решение из десяти. Поэтому
     изменение идёт от предыдущего состояния, а запись в хранилище —
     эффектом на изменившиеся черновики. */
  useEffect(() => {
    // Пока человек ничего не трогал, писать нечего: пустая запись поверх
    // восстановленной стёрла бы ровно то, что мы только что прочитали.
    if (!touched.current) {
      return;
    }

    try {
      localStorage.setItem(storageKey, JSON.stringify(drafts));
    } catch {
      // Не сохранилось — работа всё равно продолжается, просто её нельзя
      // будет вернуть после закрытия вкладки.
    }
  }, [drafts, storageKey]);

  function change(candidate: Candidate, patch: Partial<Draft>): void {
    touched.current = true;

    setDrafts((was) => {
      const previous: Draft = was[candidate.id] ?? {
        target: "",
        kind: candidate.kind,
        reject: false,
      };

      return { ...was, [candidate.id]: { ...previous, ...patch } };
    });
  }

  const undecided = candidates.filter((item) => item.status === "new");

  /* Решённые строки — те, где человек что-то сделал: набрал перевод,
     отметил «не термин» или выбрал разряд, которому перевод не нужен. */
  const decisions = useMemo((): Decision[] => {
    const ready: Decision[] = [];

    for (const candidate of undecided) {
      const draft = drafts[candidate.id];

      if (draft === undefined) {
        continue;
      }

      if (draft.reject) {
        ready.push({ candidate_id: candidate.id, accept: false });
        continue;
      }

      const target = draft.target.trim();
      const kind = draft.kind || candidate.kind;

      // У непереводимого перевод совпадает с исходником, и требовать его —
      // заставлять человека копировать строку.
      if (target === "" && kind !== "do_not_translate") {
        continue;
      }

      ready.push({
        candidate_id: candidate.id,
        accept: true,
        target_term: target === "" ? undefined : target,
        kind,
      });
    }

    return ready;
  }, [drafts, undecided]);

  function save(): void {
    setError(null);
    setReport(null);

    start(async () => {
      const answer = await decideTerms(documentId, decisions);

      if (answer.error !== undefined) {
        setError(answer.error);
        return;
      }

      // Записанное перестаёт быть черновиком: оно уже в словаре, и вернуть
      // его на страницу после перезагрузки значит предложить решить дважды.
      touched.current = true;

      setDrafts((was) => {
        const left = { ...was };

        for (const decision of decisions) {
          delete left[decision.candidate_id];
        }

        return left;
      });
      setReport(answer.report ?? null);
      router.refresh();
    });
  }

  if (undecided.length === 0) {
    return (
      <section className="tile wk-call">
        <h3>Все кандидаты решены</h3>
        <p>
          По этой книге решать больше нечего — перевод можно запускать. Новые
          кандидаты появятся, если книгу разобрать заново из исправленного
          файла.
        </p>
        {report !== null && <Summary report={report} />}
      </section>
    );
  }

  return (
    <>
      <section className="tile">
        <div className="tile__head">
          <h3>Кандидаты в словарь</h3>
          <span className="tile__note">
            {thousands(undecided.length)} без решения · сначала частые
          </span>
        </div>

        <div className="tm-list">
          {undecided.map((candidate) => {
            const draft = drafts[candidate.id];
            const rejected = draft?.reject === true;

            return (
              <div className={rejected ? "tm-row is-off" : "tm-row"} key={candidate.id}>
                <div className="tm-row__term">
                  <b>{candidate.source_term}</b>
                  <span className="tile__note">
                    {thousands(candidate.frequency)}{" "}
                    {plural(candidate.frequency, "раз", "раза", "раз")} · сегмент{" "}
                    {candidate.first_position + 1}
                  </span>
                  {candidate.expansion !== null && (
                    <span className="tm-row__exp">{candidate.expansion}</span>
                  )}
                </div>

                <p className="tm-row__sample">{candidate.sample}</p>

                <div className="tm-row__decide">
                  <input
                    className="tm-input"
                    type="text"
                    value={draft?.target ?? ""}
                    placeholder="Перевод"
                    disabled={rejected || busy}
                    maxLength={300}
                    onChange={(event) => change(candidate, { target: event.target.value })}
                  />

                  <select
                    className="tm-kind"
                    value={draft?.kind ?? candidate.kind}
                    disabled={rejected || busy}
                    title={GLOSSARY_KIND_HINT[draft?.kind ?? candidate.kind]}
                    onChange={(event) => change(candidate, { kind: event.target.value })}
                  >
                    {KINDS.map((kind) => (
                      <option key={kind} value={kind}>
                        {GLOSSARY_KIND[kind]}
                      </option>
                    ))}
                  </select>

                  <button
                    className={rejected ? "tm-skip is-on" : "tm-skip"}
                    type="button"
                    disabled={busy}
                    onClick={() => change(candidate, { reject: !rejected })}
                  >
                    {rejected ? "Вернуть" : "Не термин"}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* Полоса записи прилипает к низу экрана: список длинный, и уходить
          за кнопкой в самый конец, решив пять терминов, незачем. */}
      <div className="tm-bar">
        <span>
          Решено {thousands(decisions.length)} из {thousands(undecided.length)}
        </span>

        <button
          className="btn btn--primary btn--small"
          type="button"
          onClick={save}
          disabled={busy || decisions.length === 0}
        >
          {busy ? "Записываем…" : "Записать решения"}
        </button>
      </div>

      {error !== null && (
        <p className="form__error" role="alert">
          {error}
        </p>
      )}

      {report !== null && <Summary report={report} />}
    </>
  );
}

function Summary({ report }: { report: Report }) {
  return (
    <p className="wk-note" role="status">
      <span aria-hidden="true">✅</span> Принято {thousands(report.accepted)}, отклонено{" "}
      {thousands(report.rejected)}.{" "}
      {report.remaining === 0
        ? "Нерешённых не осталось — перевод можно запускать."
        : `Осталось без решения ${thousands(report.remaining)} — пока они есть, перевод не начнётся.`}
    </p>
  );
}
