"use client";

/* Завести термин руками.

   Заведённое руками считается решённым: человек, набравший перевод, уже
   договорился с собой — запись сразу подтверждённая. Повтор того же
   термина — правка, а не ошибка: API уточняет перевод, а не заводит
   второй. */

import { useActionState } from "react";

import { GLOSSARY_KIND, GLOSSARY_KIND_HINT } from "../labels";
import { addTerm, type AddResult } from "./actions";
import type { Pair } from "./page";

const EMPTY: AddResult = {};
const KINDS = Object.keys(GLOSSARY_KIND);

export function AddTerm({ pairs }: { pairs: Pair[] }) {
  const [state, action, busy] = useActionState(addTerm, EMPTY);

  return (
    <section className="tile gl-block">
      <div className="tile__head">
        <h3>Завести термин</h3>
        <span className="tile__note">сразу подтверждённым</span>
      </div>

      {pairs.length === 0 ? (
        <p className="tile__empty">
          Термин привязан к языковой паре, а пара задаётся проектом. Заведите
          проект — и здесь появится форма.
        </p>
      ) : (
        <form key={state.at ?? 0} action={action} className="gl-add">
          <label className="field">
            <span>Термин</span>
            <input name="source_term" required maxLength={300} placeholder="valve" />
          </label>

          <label className="field">
            <span>Перевод</span>
            <input name="target_term" required maxLength={300} placeholder="клапан" />
          </label>

          <label className="field">
            <span>Разряд</span>
            <select name="kind" defaultValue="term">
              {KINDS.map((kind) => (
                <option key={kind} value={kind} title={GLOSSARY_KIND_HINT[kind]}>
                  {GLOSSARY_KIND[kind]}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span>Пара</span>
            <select name="pair" defaultValue={pairs[0]?.value}>
              {pairs.map((pair) => (
                <option key={pair.value} value={pair.value}>
                  {pair.source} → {pair.target}
                </option>
              ))}
            </select>
          </label>

          <label className="field gl-add__note">
            <span>Примечание</span>
            <input
              name="note"
              maxLength={1000}
              placeholder="Чем этот «клапан» отличается от соседнего"
            />
          </label>

          <button className="btn btn--primary" type="submit" disabled={busy}>
            {busy ? "Записываем…" : "Добавить"}
          </button>
        </form>
      )}

      {state.error !== undefined && (
        <p className="form__error" role="alert">
          {state.error}
        </p>
      )}

      {state.added !== undefined && state.error === undefined && (
        <p className="wk-note" role="status">
          <span aria-hidden="true">✅</span> Записано: <b>{state.added.source_term}</b> →{" "}
          {state.added.target_term}.
        </p>
      )}
    </section>
  );
}
