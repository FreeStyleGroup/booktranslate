"use client";

/* Одобрение терминов загрузки в общий словарь.

   Отмечаются галочками, тематика — одна на пачку: одобряют обычно весь
   словарь заказчика, и он весь про одно. Тематика подставляется из
   настроек пространства-донора, если оно её указало, — но выбирает
   администратор: он отвечает за то, куда термин попадёт. */

import { useActionState, useState } from "react";

import type { GlossaryTerm } from "../../lib/work";
import { GLOSSARY_KIND, GLOSSARY_STATUS, thousands } from "../../app/labels";
import { publishTerms, type PublishState } from "../actions";

const EMPTY: PublishState = {};

type Subject = { id: string; title: string };

export function PublishForm({
  upload,
  terms,
  subjects,
  suggested,
}: {
  upload: string;
  terms: GlossaryTerm[];
  subjects: Subject[];
  suggested: string | null;
}) {
  const [state, action, busy] = useActionState(publishTerms, EMPTY);
  const [chosen, setChosen] = useState<Set<string>>(() => new Set(terms.map((term) => term.id)));

  function toggle(id: string): void {
    setChosen((was) => {
      const next = new Set(was);

      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }

      return next;
    });
  }

  const all = chosen.size === terms.length;

  return (
    <form action={action} className="adm-publish">
      <input type="hidden" name="upload" value={upload} />

      <div className="adm-publish__bar">
        <label className="adm-publish__all">
          <input
            type="checkbox"
            checked={all}
            onChange={() =>
              setChosen(all ? new Set() : new Set(terms.map((term) => term.id)))
            }
          />
          <span>
            Отмечено {thousands(chosen.size)} из {thousands(terms.length)}
          </span>
        </label>

        <label className="field adm-publish__subject">
          <span>Тематика</span>
          <select name="subject" defaultValue={suggested ?? ""} required>
            <option value="">Выберите…</option>
            {subjects.map((subject) => (
              <option key={subject.id} value={subject.id}>
                {subject.title}
              </option>
            ))}
          </select>
        </label>

        <button
          className="btn btn--primary btn--small"
          type="submit"
          disabled={busy || chosen.size === 0}
        >
          {busy ? "Одобряем…" : "В общий словарь"}
        </button>
      </div>

      {state.error !== undefined && (
        <p className="form__error" role="alert">
          {state.error}
        </p>
      )}

      {state.published !== undefined && state.error === undefined && (
        <p className="adm-note" role="status">
          <span aria-hidden="true">✅</span> В общий словарь попало{" "}
          {thousands(state.published)}: повторно одобренные уточнены, а не удвоены.
        </p>
      )}

      <div className="adm-terms">
        {terms.map((term) => (
          <label className="adm-terms__row" key={term.id}>
            <input
              type="checkbox"
              name="term"
              value={term.id}
              checked={chosen.has(term.id)}
              onChange={() => toggle(term.id)}
            />
            <span className="adm-terms__source">
              <b>{term.source_term}</b>
              {term.note !== null && term.note !== "" && <small>{term.note}</small>}
            </span>
            <span className="adm-terms__target">{term.target_term}</span>
            <span className="adm-table__soft">{GLOSSARY_KIND[term.kind]}</span>
            <span className="adm-table__soft">{GLOSSARY_STATUS[term.status]}</span>
          </label>
        ))}
      </div>
    </form>
  );
}
