"use client";

/* Запуск терминологического прохода.

   Порог частоты вынесен в форму, а не зашит: на руководстве в тридцать
   страниц двойка нормальна, на книге в четыреста по ней наберётся список
   длиннее, чем человек станет разбирать. Значение по умолчанию — два, и
   поднимать его осмысленно после первого же взгляда на длину списка. */

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { extractTerms } from "./actions";

export function ExtractButton({
  documentId,
  again,
}: {
  documentId: string;
  again?: boolean;
}) {
  const router = useRouter();
  const [frequency, setFrequency] = useState(2);
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();

  function run(): void {
    setError(null);

    start(async () => {
      const answer = await extractTerms(documentId, frequency);

      if (answer.error !== undefined) {
        setError(answer.error);
        return;
      }

      router.refresh();
    });
  }

  return (
    <>
      <div className="tm-run">
        <label className="field">
          <span>Встречается не реже чем</span>
          <select
            value={frequency}
            disabled={busy}
            onChange={(event) => setFrequency(Number(event.target.value))}
          >
            <option value={2}>2 раза</option>
            <option value={3}>3 раза</option>
            <option value={5}>5 раз</option>
            <option value={10}>10 раз</option>
            <option value={20}>20 раз</option>
          </select>
        </label>

        <button
          className={again === true ? "btn btn--ghost" : "btn btn--primary"}
          type="button"
          onClick={run}
          disabled={busy}
        >
          {busy ? "Идём по книге…" : again === true ? "Пройти заново" : "Собрать кандидатов"}
        </button>
      </div>

      {error !== null && (
        <p className="form__error" role="alert">
          {error}
        </p>
      )}
    </>
  );
}
