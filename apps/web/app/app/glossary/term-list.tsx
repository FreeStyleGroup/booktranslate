"use client";

/* Список терминов с правкой на месте.

   Перевод, разряд и состояние правятся прямо в строке: перепроверка
   словаря — это сотня мелких решений, и уводить каждое на отдельную
   страницу значит не получить ни одного. Перевод уходит по потере
   фокуса или по Enter, списки — сразу при выборе. Отказ API появляется
   над списком словами.

   Без права правки строки читаются как текст: кнопки, ведущие к отказу,
   не рисуются. */

import { useState, useTransition } from "react";

import type { GlossaryKind, GlossaryStatus, GlossaryTerm } from "../../lib/work";
import {
  GLOSSARY_KIND,
  GLOSSARY_KIND_HINT,
  GLOSSARY_STATUS,
  GLOSSARY_STATUS_HINT,
  glossarySource,
} from "../labels";
import { deleteTerm, updateTerm, type TermChange } from "./actions";

const KINDS = Object.keys(GLOSSARY_KIND) as GlossaryKind[];
const STATUSES = Object.keys(GLOSSARY_STATUS) as GlossaryStatus[];

const STATUS_CHIP: Record<GlossaryStatus, string> = {
  proposed: "chip chip--info",
  confirmed: "chip chip--ok",
  needs_review: "chip chip--warn",
  needs_unification: "chip chip--warn",
  retired: "chip chip--danger",
};

export function TermList({ terms, edits }: { terms: GlossaryTerm[]; edits: boolean }) {
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  function run(action: () => Promise<{ error?: string }>): void {
    setError(null);
    start(async () => {
      const result = await action();

      if (result.error !== undefined) {
        setError(result.error);
      }
    });
  }

  function change(term: GlossaryTerm, patch: TermChange): void {
    run(() => updateTerm(term.id, patch));
  }

  return (
    <>
      {error !== null && (
        <p className="form__error" role="alert">
          {error}
        </p>
      )}

      <div className="gl-list">
        {terms.map((term) => (
          <div
            className={term.status === "retired" ? "gl-row is-off" : "gl-row"}
            key={term.id}
          >
            <div className="gl-row__source">
              <b>{term.source_term}</b>
              <span className="tile__note">
                {term.source_language} → {term.target_language} · {glossarySource(term.source)}
                {term.project_id !== null && " · проект"}
              </span>
              {term.note !== null && term.note !== "" && (
                <span className="gl-row__note">{term.note}</span>
              )}
            </div>

            {edits ? (
              <>
                <input
                  className="gl-input"
                  type="text"
                  defaultValue={term.target_term}
                  maxLength={300}
                  disabled={pending}
                  aria-label={`Перевод: ${term.source_term}`}
                  onBlur={(event) => {
                    const value = event.target.value.trim();

                    if (value !== "" && value !== term.target_term) {
                      change(term, { target_term: value });
                    }
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.currentTarget.blur();
                    }
                  }}
                />

                <select
                  className="gl-select"
                  value={term.kind}
                  disabled={pending}
                  title={GLOSSARY_KIND_HINT[term.kind]}
                  aria-label={`Разряд: ${term.source_term}`}
                  onChange={(event) => change(term, { kind: event.target.value as GlossaryKind })}
                >
                  {KINDS.map((kind) => (
                    <option key={kind} value={kind}>
                      {GLOSSARY_KIND[kind]}
                    </option>
                  ))}
                </select>

                <select
                  className="gl-select"
                  value={term.status}
                  disabled={pending}
                  title={GLOSSARY_STATUS_HINT[term.status]}
                  aria-label={`Состояние: ${term.source_term}`}
                  onChange={(event) =>
                    change(term, { status: event.target.value as GlossaryStatus })
                  }
                >
                  {STATUSES.map((status) => (
                    <option key={status} value={status}>
                      {GLOSSARY_STATUS[status]}
                    </option>
                  ))}
                </select>

                <button
                  className="wk-kill"
                  type="button"
                  disabled={pending}
                  aria-label={`Удалить: ${term.source_term}`}
                  title="Удалить из словаря"
                  onClick={() => {
                    if (confirm(`Удалить «${term.source_term}» из словаря?`)) {
                      run(() => deleteTerm(term.id));
                    }
                  }}
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true" width="16" height="16">
                    <path
                      d="M6 6l12 12M18 6L6 18"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                    />
                  </svg>
                </button>
              </>
            ) : (
              <>
                <span className="gl-row__target">{term.target_term}</span>
                <span className="tile__note">{GLOSSARY_KIND[term.kind]}</span>
                <span className={STATUS_CHIP[term.status]}>{GLOSSARY_STATUS[term.status]}</span>
              </>
            )}
          </div>
        ))}
      </div>
    </>
  );
}
