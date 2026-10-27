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

import type { FirstUseRule, GlossaryKind, GlossaryStatus, GlossaryTerm } from "../../lib/work";
import {
  FIRST_USE_HINT,
  FIRST_USE_RULE,
  GLOSSARY_KIND,
  GLOSSARY_KIND_HINT,
  GLOSSARY_STATUS,
  GLOSSARY_STATUS_HINT,
  glossarySource,
} from "../labels";
import { deleteTerm, updateTerm, type TermChange } from "./actions";
import { ReportError } from "../ui/toast";

const KINDS = Object.keys(GLOSSARY_KIND) as GlossaryKind[];
const STATUSES = Object.keys(GLOSSARY_STATUS) as GlossaryStatus[];
const RULES = Object.keys(FIRST_USE_RULE) as FirstUseRule[];

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
      <ReportError error={error} />

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

            <TermMore
              term={term}
              edits={edits}
              pending={pending}
              onSave={(patch) => change(term, patch)}
            />
          </div>
        ))}
      </div>
    </>
  );
}

/** Уточнения решения: варианты, область, первое употребление, обязательность.

   Под раскрытием, а не в строке: решают их реже, чем перевод и
   состояние, а в строке они сжали бы перевод до слова. Свёрнутое
   раскрытие само говорит, что уточнено, — его не нужно открывать, чтобы
   увидеть варианты. */
function TermMore({
  term,
  edits,
  pending,
  onSave,
}: {
  term: GlossaryTerm;
  edits: boolean;
  pending: boolean;
  onSave: (patch: TermChange) => void;
}) {
  const facts = [
    term.allowed_variants.length > 0 ? `варианты: ${term.allowed_variants.join("; ")}` : null,
    term.domain,
    term.first_use_rule !== "none" ? FIRST_USE_RULE[term.first_use_rule].toLowerCase() : null,
    term.mandatory ? null : "необязательный",
  ].filter((fact) => fact !== null);

  if (!edits) {
    return facts.length === 0 ? null : <p className="gl-more__facts">{facts.join(" · ")}</p>;
  }

  const untranslatable = term.kind === "do_not_translate";

  return (
    <details className="gl-more">
      <summary>
        {facts.length === 0 ? "Варианты, область, первое употребление" : facts.join(" · ")}
      </summary>

      <form
        className="gl-more__form"
        onSubmit={(event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          const domain = String(form.get("domain") ?? "").trim();

          onSave({
            // У непереводимого поле закрыто и в форму не попадает — его
            // варианты не трогаем, а не стираем.
            ...(untranslatable
              ? {}
              : {
                  allowed_variants: String(form.get("variants") ?? "")
                    .split(/\r?\n/)
                    .map((line) => line.trim())
                    .filter((line) => line !== ""),
                }),
            domain: domain === "" ? null : domain,
            first_use_rule: String(form.get("first_use_rule")) as FirstUseRule,
            mandatory: form.get("mandatory") === "on",
          });
        }}
      >
        <label className="field">
          <span>Допустимые варианты — по одному в строке</span>
          <textarea
            name="variants"
            rows={3}
            defaultValue={term.allowed_variants.join("\n")}
            disabled={pending || untranslatable}
            placeholder={untranslatable ? "у непереводимого вариантов нет" : "клапан сброса"}
          />
        </label>

        <label className="field">
          <span>Область</span>
          <input
            name="domain"
            maxLength={120}
            defaultValue={term.domain ?? ""}
            disabled={pending}
            placeholder="гидравлика"
          />
        </label>

        <label className="field">
          <span>При первом употреблении</span>
          <select
            name="first_use_rule"
            defaultValue={term.first_use_rule}
            disabled={pending}
            title={FIRST_USE_HINT[term.first_use_rule]}
          >
            {RULES.map((rule) => (
              <option key={rule} value={rule} title={FIRST_USE_HINT[rule]}>
                {FIRST_USE_RULE[rule]}
              </option>
            ))}
          </select>
        </label>

        <label className="gl-check">
          <input
            type="checkbox"
            name="mandatory"
            defaultChecked={term.mandatory}
            disabled={pending}
          />
          <span>Обязательный — без него перевод блока помечается</span>
        </label>

        <button className="btn btn--ghost btn--small" type="submit" disabled={pending}>
          Сохранить уточнения
        </button>
      </form>
    </details>
  );
}
