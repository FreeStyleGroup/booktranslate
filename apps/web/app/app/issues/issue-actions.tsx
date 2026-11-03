"use client";

/* Действия на карточке замечания.

   Кнопки рисуются по списку, который прислал API: таблицы переходов и прав здесь нет, и
   разойтись с сервером ей не с чем. Текст обязателен там, где без него решение ничем не
   объяснено: отклонить, спросить, ответить, открыть заново. */

import { useRouter } from "next/navigation";
import { useRef, useState, useTransition } from "react";

import type { IssueCandidate, IssueCategory, IssueDetail, IssueSeverity } from "../../lib/work";
import {
  ISSUE_CATEGORY_LABEL,
  ISSUE_CATEGORY_ORDER,
  ISSUE_SEVERITY_LABEL,
  ISSUE_SEVERITY_ORDER,
} from "../labels";
import { ReportError, useToast } from "../ui/toast";
import {
  assignIssue,
  decideIssue,
  fixIssue,
  reclassifyIssue,
  restoreIssue,
  type IssueDecision,
  type IssueResult,
} from "./actions";

type Described = {
  decision: IssueDecision;
  label: string;
  done: string;
  // Обязателен ли текст; `null` — поле вовсе не нужно.
  note: "required" | "optional";
  placeholder: string;
  primary?: boolean;
};

const DECISIONS: Described[] = [
  {
    decision: "confirm",
    label: "Подтвердить",
    done: "Ошибка подтверждена",
    note: "optional",
    placeholder: "Что подтвердила сверка с оригиналом",
    primary: true,
  },
  {
    decision: "reject",
    label: "Отклонить",
    done: "Замечание отклонено: перевод не изменился",
    note: "required",
    placeholder: "Почему это не ошибка",
  },
  {
    decision: "request_clarification",
    label: "Уточнить",
    done: "Вопрос записан",
    note: "required",
    placeholder: "Что нужно уточнить",
  },
  {
    decision: "answer_clarification",
    label: "Ответить на вопрос",
    done: "Ответ записан: замечание снова ждёт решения",
    note: "required",
    placeholder: "Ответ на вопрос",
    primary: true,
  },
  {
    decision: "verify",
    label: "Исправление проверено",
    done: "Исправление проверено",
    note: "optional",
    placeholder: "Что проверили",
    primary: true,
  },
  {
    decision: "close",
    label: "Закрыть",
    done: "Замечание закрыто",
    note: "optional",
    placeholder: "Итог",
    primary: true,
  },
  {
    decision: "reopen",
    label: "Открыть заново",
    done: "Замечание открыто заново",
    note: "required",
    placeholder: "Почему открываем заново",
  },
  {
    decision: "archive",
    label: "В архив",
    done: "Замечание в архиве: запись осталась",
    note: "optional",
    placeholder: "Зачем убираем",
  },
  {
    decision: "comment",
    label: "Комментарий",
    done: "Комментарий записан",
    note: "required",
    placeholder: "Комментарий",
  },
];

export function IssueActions({
  issue,
  members,
}: {
  issue: IssueDetail;
  members: { user_id: string; email: string }[];
}) {
  const [chosen, setChosen] = useState<Described | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const form = useRef<HTMLFormElement>(null);
  const router = useRouter();
  const toast = useToast();

  function run(action: () => Promise<IssueResult>, done: string): void {
    setError(null);

    start(async () => {
      const result = await action();

      if (result.error !== undefined) {
        setError(result.error);
        return;
      }

      setChosen(null);
      form.current?.reset();
      toast.ok(done);
      router.refresh();
    });
  }

  const available = DECISIONS.filter((item) => issue.actions.includes(item.decision));

  if (issue.actions.length === 0) {
    return null;
  }

  return (
    <section className="tile">
      <div className="tile__head">
        <h3>Решение</h3>
      </div>

      {issue.review_note !== null && (
        <p className="bk-mismatch" role="status">
          <span aria-hidden="true">👥</span>
          <span>{issue.review_note}</span>
        </p>
      )}

      {issue.actions.includes("restore") && (
        <div className="wk-actions">
          <button
            className="btn btn--ghost"
            type="button"
            disabled={pending}
            onClick={() => run(() => restoreIssue(issue.id), "Замечание возвращено из архива")}
          >
            Вернуть из архива
          </button>
        </div>
      )}

      {available.length > 0 && (
        <div className="wk-actions">
          {available.map((item) => (
            <button
              key={item.decision}
              className={item.primary ? "btn btn--primary" : "btn btn--ghost"}
              type="button"
              disabled={pending}
              aria-pressed={chosen?.decision === item.decision}
              onClick={() => setChosen(item)}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}

      {chosen !== null && (
        <form
          className="is-form"
          ref={form}
          onSubmit={(event) => {
            event.preventDefault();
            const note = String(new FormData(event.currentTarget).get("note") ?? "");
            run(() => decideIssue(issue.id, chosen.decision, note), chosen.done);
          }}
        >
          <label className="field">
            <span>
              {chosen.label}: {chosen.note === "required" ? "обязательно напишите" : "можно пояснить"}
            </span>
            <textarea
              name="note"
              required={chosen.note === "required"}
              maxLength={4000}
              rows={3}
              placeholder={chosen.placeholder}
              // Поле открыто нажатием: печатать человек собирался именно здесь.
              autoFocus
            />
          </label>

          <div className="wk-actions">
            <button className="btn btn--primary" type="submit" disabled={pending}>
              {pending ? "Записываем…" : "Записать"}
            </button>
            <button
              className="btn btn--ghost"
              type="button"
              disabled={pending}
              onClick={() => setChosen(null)}
            >
              Отмена
            </button>
          </div>
        </form>
      )}

      {issue.actions.includes("fix") && (
        <FixBlock
          candidates={issue.candidates}
          pending={pending}
          onFix={(revisionId) =>
            run(() => fixIssue(issue.id, revisionId, ""), "Исправление записано")
          }
        />
      )}

      {issue.actions.includes("reclassify") && (
        <Reclassify
          issue={issue}
          pending={pending}
          onSave={(change) =>
            run(() => reclassifyIssue(issue.id, change), "Классификация изменена")
          }
        />
      )}

      {issue.actions.includes("assign") && members.length > 0 && (
        <label className="field is-assign">
          <span>Кому поручено</span>
          <select
            value={issue.assignee_id ?? ""}
            disabled={pending}
            onChange={(event) =>
              run(
                () => assignIssue(issue.id, event.target.value === "" ? null : event.target.value),
                "Назначение записано",
              )
            }
          >
            <option value="">Никому</option>
            {members.map((member) => (
              <option key={member.user_id} value={member.user_id}>
                {member.email}
              </option>
            ))}
          </select>
        </label>
      )}

      <ReportError error={error} />
    </section>
  );
}

function FixBlock({
  candidates,
  pending,
  onFix,
}: {
  candidates: IssueCandidate[];
  pending: boolean;
  onFix: (revisionId: string) => void;
}) {
  if (candidates.length === 0) {
    return (
      <p className="tile__note">
        Исправить пока нечем: у текста нет новой редакции. Переведите блок заново и сделайте вариант
        текущим — тогда замечание можно будет связать с ним.
      </p>
    );
  }

  return (
    <div className="is-candidates">
      <h4>Чем исправлено</h4>
      {candidates.map((item) => (
        <div className="is-candidate" key={item.revision_id}>
          <p className="tile__note">
            {item.block_code} · редакция {item.revision_no}
          </p>
          <p className="bk-block-text">{item.text}</p>
          <button
            className="btn btn--primary btn--small"
            type="button"
            disabled={pending}
            onClick={() => onFix(item.revision_id)}
          >
            Исправлено этой редакцией
          </button>
        </div>
      ))}
    </div>
  );
}

function Reclassify({
  issue,
  pending,
  onSave,
}: {
  issue: IssueDetail;
  pending: boolean;
  onSave: (change: { reason: string; category: IssueCategory; severity: IssueSeverity }) => void;
}) {
  return (
    <details className="bk-raw">
      <summary>Изменить категорию или серьёзность</summary>

      <form
        className="is-form"
        onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);

          onSave({
            reason: String(data.get("reason") ?? ""),
            category: String(data.get("category")) as IssueCategory,
            severity: String(data.get("severity")) as IssueSeverity,
          });
        }}
      >
        <div className="is-form__row">
          <label className="field">
            <span>Категория</span>
            <select name="category" defaultValue={issue.category}>
              {ISSUE_CATEGORY_ORDER.map((value) => (
                <option key={value} value={value}>
                  {ISSUE_CATEGORY_LABEL[value]}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span>Серьёзность</span>
            <select name="severity" defaultValue={issue.severity}>
              {ISSUE_SEVERITY_ORDER.map((value) => (
                <option key={value} value={value}>
                  {ISSUE_SEVERITY_LABEL[value]}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label className="field">
          <span>Причина</span>
          <textarea name="reason" required maxLength={4000} rows={2} />
        </label>

        <div className="wk-actions">
          <button className="btn btn--ghost" type="submit" disabled={pending}>
            Записать
          </button>
        </div>
      </form>
    </details>
  );
}
