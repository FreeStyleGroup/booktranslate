"use client";

/* Пары памяти с правкой на месте.

   Перевод правится прямо в строке и уходит по потере фокуса: поправленная
   пара становится человеческой и дальше вытесняет машинный вариант. Снятая
   пара из памяти исчезает — следующий такой же текст уйдёт в модель
   заново, и об этом спрашивается перед снятием.

   Без права правки строки читаются как текст. */

import { useState, useTransition } from "react";

import type { TranslationUnit } from "../../lib/work";
import { plural, thousands, when } from "../labels";
import { deleteUnit, updateUnit } from "./actions";

/** Откуда перевод — словами. */
function originLabel(origin: string): string {
  return origin === "human" ? "правка человека" : `модель ${origin}`;
}

export function UnitList({ units, edits }: { units: TranslationUnit[]; edits: boolean }) {
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

  return (
    <>
      {error !== null && (
        <p className="form__error" role="alert">
          {error}
        </p>
      )}

      <div className="mm-list">
        {units.map((unit) => (
          <div className={unit.origin === "human" ? "mm-row is-human" : "mm-row"} key={unit.id}>
            <div className="mm-row__source">
              <p>{unit.source_text}</p>
              <span className="tile__note">
                {unit.source_language} → {unit.target_language} · {originLabel(unit.origin)} ·{" "}
                {unit.hits === 0
                  ? "ещё не пригодилась"
                  : `пригодилась ${thousands(unit.hits)} ${plural(unit.hits, "раз", "раза", "раз")}`}{" "}
                · {when(unit.updated_at)}
              </span>
            </div>

            {edits ? (
              <>
                <textarea
                  className="mm-input"
                  defaultValue={unit.target_text}
                  rows={2}
                  maxLength={20000}
                  disabled={pending}
                  aria-label={`Перевод: ${unit.source_text.slice(0, 60)}`}
                  onBlur={(event) => {
                    const value = event.target.value.trim();

                    if (value !== "" && value !== unit.target_text) {
                      run(() => updateUnit(unit.id, value));
                    }
                  }}
                />

                <button
                  className="wk-kill"
                  type="button"
                  disabled={pending}
                  aria-label="Снять пару из памяти"
                  title="Снять из памяти"
                  onClick={() => {
                    if (
                      confirm(
                        "Снять пару из памяти? Следующий такой же текст уйдёт в модель заново.",
                      )
                    ) {
                      run(() => deleteUnit(unit.id));
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
              <p className="mm-row__target">{unit.target_text}</p>
            )}
          </div>
        ))}
      </div>
    </>
  );
}
