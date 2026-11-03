"use client";

/* Регрессия: что могло задеть исправление.

   Правка не расходится по книге сама. Человек видит затронутые места и решает: повтору — то же
   исправление, другому месту — «не затронуто» или своё замечание. Безопасные повторы отмечены
   заранее: их текст совпадал с исправленным дословно. Пока обязательные места не решены, замечание
   не закроется. */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import type {
  IssueCategory,
  IssueDetail,
  IssueSeverity,
  RegressionItem,
  RegressionRun,
} from "../../lib/work";
import {
  ISSUE_CATEGORY_LABEL,
  ISSUE_CATEGORY_ORDER,
  ISSUE_SEVERITY_LABEL,
  ISSUE_SEVERITY_ORDER,
  REGRESSION_DECISION_LABEL,
  REGRESSION_KIND_LABEL,
  plural,
  thousands,
} from "../labels";
import { ReportError, useToast } from "../ui/toast";
import { applyRegression, decideRegression, type IssueResult } from "./actions";

export function RegressionPanel({
  issue,
  run,
  canAct,
}: {
  issue: IssueDetail;
  run: RegressionRun;
  canAct: boolean;
}) {
  const repeats = run.items.filter((item) => item.proposed_text !== null && item.decision === "pending");
  const [chosen, setChosen] = useState<string[]>(
    repeats.filter((item) => item.safe && !item.final_candidate).map((item) => item.id),
  );
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const router = useRouter();
  const toast = useToast();

  const open = canAct && run.status === "open";
  const finalChosen = repeats.some((item) => item.final_candidate && chosen.includes(item.id));

  function act(action: () => Promise<IssueResult>, done: string): void {
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

  return (
    <section className="tile">
      <div className="tile__head">
        <h3>Регрессия</h3>
        <span className={run.status === "completed" ? "chip chip--ok" : "chip chip--warn"}>
          {run.status === "completed"
            ? "завершена"
            : run.status === "superseded"
              ? "устарела"
              : `не решено: ${thousands(run.pending)}`}
        </span>
      </div>

      <p className="tile__note">
        {run.items.length === 0
          ? "Связанных мест нет: исправление ничего больше не задевает."
          : `Затронуто ${thousands(run.items.length)} ${plural(run.items.length, "место", "места", "мест")}. Сами по себе они не меняются.`}
        {run.status === "open" && run.pending > 0 && " Пока обязательные места не решены, замечание не закроется."}
      </p>

      {run.items.length > 0 && (
        <ul className="is-regression">
          {run.items.map((item) => (
            <Row
              key={item.id}
              item={item}
              issue={issue}
              open={open}
              pending={pending}
              checked={chosen.includes(item.id)}
              onToggle={(on) =>
                setChosen((before) =>
                  on ? [...before, item.id] : before.filter((id) => id !== item.id),
                )
              }
              onDecide={(payload, done) =>
                act(() => decideRegression(item.id, issue.id, payload), done)
              }
            />
          ))}
        </ul>
      )}

      {open && repeats.length > 0 && (
        <div className="is-form">
          {finalChosen && (
            <label className="field">
              <span>Среди выбранных есть кандидат в финальный текст: почему перезаписываем</span>
              <input
                type="text"
                maxLength={4000}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
            </label>
          )}

          <div className="wk-actions">
            <button
              className="btn btn--primary"
              type="button"
              disabled={pending || chosen.length === 0 || (finalChosen && reason.trim() === "")}
              onClick={() =>
                act(
                  () => applyRegression(run.id, issue.id, chosen, finalChosen, reason),
                  "Исправление применено к выбранным местам",
                )
              }
            >
              Применить исправление к выбранным: {thousands(chosen.length)}
            </button>
          </div>
        </div>
      )}

      <ReportError error={error} />
    </section>
  );
}

function Row({
  item,
  issue,
  open,
  pending,
  checked,
  onToggle,
  onDecide,
}: {
  item: RegressionItem;
  issue: IssueDetail;
  open: boolean;
  pending: boolean;
  checked: boolean;
  onToggle: (on: boolean) => void;
  onDecide: (
    payload: {
      affected: boolean;
      note: string | null;
      category: IssueCategory | null;
      severity: IssueSeverity | null;
    },
    done: string,
  ) => void;
}) {
  const [asking, setAsking] = useState(false);
  const chapter = `/app/books/${issue.book_id}/chapters/${issue.chapter_id}`;
  const waiting = item.decision === "pending";
  const repeat = item.proposed_text !== null;

  return (
    <li>
      <div className="is-regression__head">
        {open && waiting && repeat && (
          <input
            type="checkbox"
            aria-label={`Применить исправление к ${item.code}`}
            checked={checked}
            disabled={pending}
            onChange={(event) => onToggle(event.target.checked)}
          />
        )}
        {item.block_id !== null ? (
          <Link href={`${chapter}/translation/${item.block_id}`}>{item.code}</Link>
        ) : (
          <Link href={`${chapter}/objects/${item.object_id}`}>{item.code}</Link>
        )}
        <span className="tile__note">{REGRESSION_KIND_LABEL[item.kind]}</span>
        {!item.required && <span className="chip">для сведения</span>}
        {repeat && item.safe && <span className="chip chip--ok">текст совпадал</span>}
        {repeat && !item.safe && <span className="chip chip--warn">контекст может отличаться</span>}
        {item.final_candidate && <span className="chip chip--warn">кандидат в финальный текст</span>}
        {!waiting && <span className="chip chip--info">{REGRESSION_DECISION_LABEL[item.decision]}</span>}
        {item.child_issue_id !== null && (
          <Link href={`/app/issues/${item.child_issue_id}`}>{item.child_code}</Link>
        )}
      </div>

      {item.current_text !== null && <p className="bk-block-text">{item.current_text}</p>}
      {item.block_id !== null && item.current_text === null && (
        <p className="tile__note">Этот блок ещё не переведён.</p>
      )}
      {item.note !== null && <p className="tile__note">{item.note}</p>}

      {open && waiting && item.required && !asking && (
        <div className="wk-actions">
          <button
            className="btn btn--ghost btn--small"
            type="button"
            disabled={pending}
            onClick={() =>
              onDecide(
                { affected: false, note: null, category: null, severity: null },
                "Отмечено: не затронуто",
              )
            }
          >
            Не затронуто
          </button>
          <button
            className="btn btn--ghost btn--small"
            type="button"
            disabled={pending}
            onClick={() => setAsking(true)}
          >
            Здесь своя ошибка
          </button>
        </div>
      )}

      {asking && (
        <form
          className="is-form"
          onSubmit={(event) => {
            event.preventDefault();
            const data = new FormData(event.currentTarget);

            onDecide(
              {
                affected: true,
                note: String(data.get("note") ?? ""),
                category: String(data.get("category")) as IssueCategory,
                severity: String(data.get("severity")) as IssueSeverity,
              },
              "Заведено дочернее замечание",
            );
            setAsking(false);
          }}
        >
          <div className="is-form__row">
            <label className="field">
              <span>Категория</span>
              <select name="category" defaultValue="translation">
                {ISSUE_CATEGORY_ORDER.map((value) => (
                  <option key={value} value={value}>
                    {ISSUE_CATEGORY_LABEL[value]}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Серьёзность</span>
              <select name="severity" defaultValue="major">
                {ISSUE_SEVERITY_ORDER.map((value) => (
                  <option key={value} value={value}>
                    {ISSUE_SEVERITY_LABEL[value]}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="field">
            <span>В чём ошибка</span>
            <textarea name="note" required maxLength={10000} rows={2} />
          </label>
          <div className="wk-actions">
            <button className="btn btn--primary btn--small" type="submit" disabled={pending}>
              Завести замечание
            </button>
            <button
              className="btn btn--ghost btn--small"
              type="button"
              onClick={() => setAsking(false)}
            >
              Отмена
            </button>
          </div>
        </form>
      )}
    </li>
  );
}
