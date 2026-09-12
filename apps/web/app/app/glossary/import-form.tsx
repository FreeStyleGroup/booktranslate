"use client";

/* Загрузка словаря из файла.

   Обычным запросом через обработчик маршрута, а не серверным действием:
   термбаза бывает больше мегабайта, а действие принимает тело в память.

   Разрешение на общий словарь — здесь, у файла, потому что решение
   принимается про конкретный словарь: «этот можно отдать площадке». Оно
   запоминается в настройках пространства и действует на следующие
   загрузки, пока его не поменяют. Менять его может владелец или
   администратор пространства — остальные видят, как оно стоит. */

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import type { GlossaryUpload } from "../../lib/work";
import { thousands, when } from "../labels";
import type { Pair } from "./page";

const ACCEPT = ".csv,.tsv,.txt,.tbx,.xml,.docx";

type Report = {
  total?: number;
  added?: number;
  updated?: number;
  skipped?: number;
  reasons?: string[];
  upload?: GlossaryUpload;
  detail?: string;
};

export function ImportForm({
  pairs,
  manages,
  sharing,
  uploads,
}: {
  pairs: Pair[];
  manages: boolean;
  sharing: boolean;
  uploads: GlossaryUpload[];
}) {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null);

  async function send(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();

    if (file === null) {
      return;
    }

    const form = new FormData(event.currentTarget);
    const [source = "", target = ""] = String(form.get("pair") ?? "").split("→");

    const body = new FormData();
    body.append("file", file);
    body.append("source_language", source);
    body.append("target_language", target);
    body.append("origin", String(form.get("origin") ?? "").trim() || "файл");
    body.append("overwrite_manual", form.get("overwrite_manual") === "yes" ? "true" : "false");

    // Разрешение уходит только от того, кто вправе его менять: у остальных
    // поле выключено, и API берёт настройку пространства.
    if (manages) {
      body.append("share", form.get("share") === "yes" ? "true" : "false");
    }

    setBusy(true);
    setError(null);
    setReport(null);

    try {
      const response = await fetch("/api/glossary/import", { method: "POST", body });
      const answer = (await response.json()) as Report;

      if (!response.ok) {
        setError(answer.detail ?? `Не получилось загрузить (ошибка ${response.status})`);
        return;
      }

      setReport(answer);
      setFile(null);

      if (input.current !== null) {
        input.current.value = "";
      }

      router.refresh();
    } catch {
      setError("Связь оборвалась. Попробуйте ещё раз.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="tile gl-block">
      <div className="tile__head">
        <h3>Загрузить словарь</h3>
        <span className="tile__note">CSV, TSV, TBX, реестр в DOCX</span>
      </div>

      {pairs.length === 0 ? (
        <p className="tile__empty">
          Словарь загружается в языковую пару, а пара задаётся проектом.
          Заведите проект — и здесь появится форма.
        </p>
      ) : (
        <form className="gl-import" onSubmit={(event) => void send(event)}>
          {/* Системная кнопка «Обзор…» не поддаётся оформлению и выглядит
              чужой в любой теме: настоящее поле спрятано (см. .wk-file), а
              видна своя кнопка и имя выбранного файла. */}
          <div className="field gl-import__file">
            <span>Файл</span>
            <div className="gl-pick">
              <button
                className="btn btn--ghost btn--small"
                type="button"
                disabled={busy}
                onClick={() => input.current?.click()}
              >
                Выбрать файл
              </button>
              <span className={file === null ? "gl-pick__name is-empty" : "gl-pick__name"}>
                {file === null ? "файл не выбран" : file.name}
              </span>
              <input
                ref={input}
                className="wk-file"
                type="file"
                accept={ACCEPT}
                aria-label="Файл словаря"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
            </div>
            <small>
              Таблица: колонки «source, target, note». Заведённое руками файл
              не перезаписывает.
            </small>
          </div>

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

          <label className="field">
            <span>Источник</span>
            <input name="origin" maxLength={100} placeholder="Заказчик, стандарт, база" />
          </label>

          <label className="gl-check">
            <input type="checkbox" name="overwrite_manual" value="yes" />
            <span>Перезаписать и то, что заведено вручную</span>
          </label>

          <label className="gl-check gl-check--share" title={manages ? undefined : "Меняет владелец или администратор пространства"}>
            <input
              type="checkbox"
              name="share"
              value="yes"
              defaultChecked={sharing}
              disabled={!manages}
            />
            <span>
              Разрешить площадке взять термины этого словаря в общий
              <small>
                Только термины — не текст книг. Общий словарь подсказывает
                другим пространствам той же тематики.
                {!manages && " Разрешение даёт владелец или администратор."}
              </small>
            </span>
          </label>

          <button className="btn btn--primary" type="submit" disabled={busy || file === null}>
            {busy ? "Загружаем…" : "Загрузить"}
          </button>
        </form>
      )}

      {error !== null && (
        <p className="form__error" role="alert">
          {error}
        </p>
      )}

      {report !== null && <Summary report={report} />}

      {uploads.length > 0 && <History uploads={uploads} />}
    </section>
  );
}

function Summary({ report }: { report: Report }) {
  return (
    <div className="gl-report" role="status">
      <p className="wk-note">
        <span aria-hidden="true">✅</span> Добавлено {thousands(report.added ?? 0)}, обновлено{" "}
        {thousands(report.updated ?? 0)}, пропущено {thousands(report.skipped ?? 0)} из{" "}
        {thousands(report.total ?? 0)}.
        {report.upload?.shared === true && " Термины отданы площадке — по вашему разрешению."}
      </p>

      {report.reasons !== undefined && report.reasons.length > 0 && (
        <ul className="gl-reasons">
          {report.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Что загружали: по истории видно, какой файл откуда и под каким разрешением. */
function History({ uploads }: { uploads: GlossaryUpload[] }) {
  return (
    <div className="gl-history">
      <h4>Загружали</h4>
      <ul>
        {uploads.slice(0, 8).map((upload) => (
          <li key={upload.id}>
            <b>{upload.filename}</b>
            <span className="tile__note">
              {" "}
              · {upload.origin} · {upload.source_language} → {upload.target_language} ·{" "}
              {thousands(upload.added + upload.updated)} записей · {when(upload.created_at)}
            </span>
            {upload.shared && <span className="chip chip--info">отдан площадке</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}
