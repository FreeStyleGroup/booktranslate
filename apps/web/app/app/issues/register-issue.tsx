"use client";

/* Кнопка «Зарегистрировать ошибку» на блоке и объекте.

   Подставлять нечего: код, снимки и редакцию сервер берёт сам. Человек говорит только, в чём
   ошибка и насколько она серьёзна, — и попадает на карточку уже с постоянным кодом. */

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import type { IssueCategory, IssueSeverity } from "../../lib/work";
import {
  ISSUE_CATEGORY_LABEL,
  ISSUE_CATEGORY_ORDER,
  ISSUE_SEVERITY_HINT,
  ISSUE_SEVERITY_LABEL,
  ISSUE_SEVERITY_ORDER,
} from "../labels";
import { ReportError, useToast } from "../ui/toast";
import { registerIssue } from "./actions";

export function RegisterIssue({
  blockId = null,
  objectId = null,
  category = "translation",
}: {
  blockId?: string | null;
  objectId?: string | null;
  /** С какого разряда начать: у таблицы и формулы он почти всегда свой. */
  category?: IssueCategory;
}) {
  const [severity, setSeverity] = useState<IssueSeverity>("major");
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const router = useRouter();
  const toast = useToast();

  function submit(form: FormData): void {
    setError(null);

    start(async () => {
      const result = await registerIssue({
        block_id: blockId,
        object_id: objectId,
        category: String(form.get("category")) as IssueCategory,
        severity,
        description: String(form.get("description") ?? ""),
        proposed_fix: String(form.get("proposed_fix") ?? "").trim() || null,
      });

      if (result.error !== undefined || result.id === undefined) {
        setError(result.error ?? "Сервис не ответил");
        return;
      }

      toast.ok("Ошибка зарегистрирована");
      router.push(`/app/issues/${result.id}`);
    });
  }

  return (
    <details className="tile is-register">
      <summary className="btn btn--ghost btn--small">Зарегистрировать ошибку</summary>

      <form
        className="is-form"
        onSubmit={(event) => {
          event.preventDefault();
          submit(new FormData(event.currentTarget));
        }}
      >
        <p className="tile__note">
          Текст сейчас не меняется: замечание получит постоянный код и снимок того, что вы видите, а
          исправление появится после подтверждения.
        </p>

        <div className="is-form__row">
          <label className="field">
            <span>Категория</span>
            <select name="category" defaultValue={category}>
              {ISSUE_CATEGORY_ORDER.map((value) => (
                <option key={value} value={value}>
                  {ISSUE_CATEGORY_LABEL[value]}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span>Серьёзность</span>
            <select
              value={severity}
              onChange={(event) => setSeverity(event.target.value as IssueSeverity)}
            >
              {ISSUE_SEVERITY_ORDER.map((value) => (
                <option key={value} value={value}>
                  {ISSUE_SEVERITY_LABEL[value]}
                </option>
              ))}
            </select>
            <small>{ISSUE_SEVERITY_HINT[severity]}</small>
          </label>
        </div>

        <label className="field">
          <span>В чём ошибка</span>
          <textarea name="description" required maxLength={10000} rows={3} />
        </label>

        <label className="field">
          <span>Как исправить, если знаете</span>
          <textarea name="proposed_fix" maxLength={10000} rows={2} />
        </label>

        <div className="wk-actions">
          <button className="btn btn--primary" type="submit" disabled={pending}>
            {pending ? "Регистрируем…" : "Зарегистрировать"}
          </button>
        </div>
      </form>

      <ReportError error={error} />
    </details>
  );
}
