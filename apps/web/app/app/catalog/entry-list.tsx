"use client";

/* Справки каталога.

   Справка ничего не решает: в словарь она попадает только кнопкой, то есть
   решением человека. Кнопка есть у найденных справок с предложенным
   переводом; ненайденная показана как ненайденная — это тоже знание, и
   второй раз про неё не спрашивают. */

import { useState, useTransition } from "react";

import type { CatalogEntry } from "../../lib/work";
import { GLOSSARY_KIND, when } from "../labels";
import { adoptEntry } from "./actions";

export function EntryList({ entries, edits }: { entries: CatalogEntry[]; edits: boolean }) {
  const [error, setError] = useState<string | null>(null);
  const [adopted, setAdopted] = useState<Set<string>>(new Set());
  const [pending, start] = useTransition();

  function adopt(entry: CatalogEntry): void {
    if (entry.suggested_target === null) {
      return;
    }

    const target = entry.suggested_target;

    setError(null);
    start(async () => {
      const result = await adoptEntry({
        source_term: entry.source_term,
        target_term: target,
        source_language: entry.source_language,
        target_language: entry.target_language,
        kind: entry.kind,
        reference: entry.sources.find((item) => item.url !== "")?.url ?? null,
      });

      if (result.error !== undefined) {
        setError(result.error);
        return;
      }

      setAdopted((was) => new Set(was).add(entry.id));
    });
  }

  return (
    <>
      {error !== null && (
        <p className="form__error" role="alert">
          {error}
        </p>
      )}

      <div className="ct-list">
        {entries.map((entry) => (
          <article className={entry.found ? "ct-entry" : "ct-entry is-missing"} key={entry.id}>
            <div className="ct-entry__head">
              <b>{entry.source_term}</b>
              {entry.expansion !== null && entry.expansion !== "" && (
                <span className="ct-entry__expansion">{entry.expansion}</span>
              )}
              <span className="tile__note">{GLOSSARY_KIND[entry.kind]}</span>
              <span className="tile__note">
                {entry.source_language} → {entry.target_language}
              </span>
            </div>

            {entry.found ? (
              <>
                {entry.suggested_target !== null && (
                  <p className="ct-entry__target">
                    <span className="tile__note">Источники предлагают:</span>{" "}
                    {entry.suggested_target}
                  </p>
                )}
                {entry.definition !== null && entry.definition !== "" && (
                  <p className="ct-entry__definition">{entry.definition}</p>
                )}
              </>
            ) : (
              <p className="ct-entry__definition">
                Не нашлось
                {entry.definition !== null && entry.definition !== ""
                  ? `: ${entry.definition.replace(/\.$/, "")}.`
                  : "."}{" "}
                Второй раз про это слово не спросят — только по вашей просьбе.
              </p>
            )}

            {entry.sources.length > 0 && (
              <ul className="ct-entry__sources">
                {entry.sources.map((source, index) => (
                  <li key={`${entry.id}-${index}`}>
                    {source.url !== "" ? (
                      <a href={source.url} target="_blank" rel="noopener noreferrer">
                        {source.title !== "" ? source.title : source.url}
                      </a>
                    ) : (
                      <span>{source.title}</span>
                    )}
                  </li>
                ))}
              </ul>
            )}

            <div className="ct-entry__foot">
              <span className="tile__note">
                {entry.looked_up_by} · {when(entry.checked_at)}
              </span>
              {edits &&
                entry.found &&
                entry.suggested_target !== null &&
                (adopted.has(entry.id) ? (
                  <span className="chip chip--ok">В словаре</span>
                ) : (
                  <button
                    className="btn btn--ghost btn--small"
                    type="button"
                    disabled={pending}
                    onClick={() => adopt(entry)}
                  >
                    В словарь
                  </button>
                ))}
            </div>
          </article>
        ))}
      </div>
    </>
  );
}
