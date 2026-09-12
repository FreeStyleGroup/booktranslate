"use client";

/* Подсказки из общего словаря площадки.

   Термины по тематике пространства, которых в его словаре нет. Принятый
   становится своим подтверждённым термином; непринятый всё равно уходит
   модели рекомендацией — необязательной, без замечаний к переводу. Своё
   решение по слову снимает подсказку.

   Без тематики подсказок нет, и об этом сказано с ссылкой на настройки,
   а не пустым местом. */

import Link from "next/link";
import { useState, useTransition } from "react";

import type { Suggestions } from "../../lib/work";
import { GLOSSARY_KIND, thousands } from "../labels";
import { acceptSuggestion } from "./actions";

export function SuggestionsBlock({
  suggestions,
  subjectTitle,
  edits,
}: {
  suggestions: Suggestions;
  subjectTitle: string | null;
  edits: boolean;
}) {
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  if (suggestions.subject === null) {
    return (
      <section className="tile gl-block gl-hint">
        <p>
          <b>Подсказки из общего словаря площадки.</b> Укажите тематику
          пространства в{" "}
          <Link href="/app/settings">настройках</Link> — и сюда придут термины,
          которыми поделились другие пространства той же области.
        </p>
      </section>
    );
  }

  if (suggestions.items.length === 0) {
    return null;
  }

  function accept(id: string): void {
    setError(null);
    start(async () => {
      const result = await acceptSuggestion(id);

      if (result.error !== undefined) {
        setError(result.error);
      }
    });
  }

  return (
    <section className="tile gl-block">
      <div className="tile__head">
        <h3>Подсказки из общего словаря</h3>
        <span className="tile__note">
          {subjectTitle} · {thousands(suggestions.items.length)}
        </span>
      </div>

      <p className="tile__note st-lead">
        Термины, которыми поделились пространства вашей тематики. Модель уже
        видит их рекомендацией; принятый станет вашим решением и будет
        проверяться в переводе.
      </p>

      {error !== null && (
        <p className="form__error" role="alert">
          {error}
        </p>
      )}

      <div className="gl-chips">
        {suggestions.items.map((item) => (
          <span className="gl-chip" key={item.id} title={item.note ?? undefined}>
            <b>{item.source_term}</b>
            <span aria-hidden="true">→</span>
            <span>{item.target_term}</span>
            <i>{GLOSSARY_KIND[item.kind]}</i>
            {edits && (
              <button
                type="button"
                className="gl-chip__take"
                disabled={pending}
                onClick={() => accept(item.id)}
              >
                Принять
              </button>
            )}
          </span>
        ))}
      </div>
    </section>
  );
}
