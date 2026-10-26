"use client";

/* Добавление источника в комплект книги.

   Два пути, потому что случая два. Чаще файла в сервисе ещё нет — его
   выбирают на диске и загружают сразу с ролью: один запрос вместо
   «загрузить, найти в списке, назначить роль». Реже файл уже загружен в
   проект раньше — тогда его выбирают из списка.

   Загрузка идёт обычным запросом с показом хода отправки, а не серверным
   действием: книга — это десятки мегабайт, а действие принимает тело
   целиком в память и ограничено мегабайтом. Подробно — в
   `app/api/documents/upload/route.ts`. */

import { useRouter } from "next/navigation";
import { useActionState, useRef, useState } from "react";

import type { Document, SourceRole } from "../../lib/work";
import { FORMAT_LABEL, SOURCE_ROLE_HINT, SOURCE_ROLE_LABEL, fileSize } from "../labels";
import { attachSource, type Result } from "./actions";
import { ReportError } from "../ui/toast";

// Согласовано с потолком прокси и API (deploy/Caddyfile, MAX_UPLOAD_MB).
// Здесь — чтобы сказать «файл слишком большой» до отправки, а не после
// тридцати мегабайт и отказа.
const MAX_BYTES = 50 * 1024 * 1024;

// XLIFF принимается API, но пока не разбирается, поэтому и не
// предлагается: файл, который примут и не смогут открыть, — обещание,
// которого мы не сдержим.
const ACCEPT = ".pdf,.docx,.epub,.html,.htm,.md,.markdown,.txt";

const ROLES: SourceRole[] = ["primary_text", "visual_reference", "auxiliary", "code_source"];

const EMPTY: Result = {};

type Answer = { id?: string; detail?: string };

export function AddSource({
  bookId,
  projectId,
  free,
  hasPrimary,
}: {
  bookId: string;
  projectId: string;
  /** Файлы проекта, ещё не входящие ни в одну книгу. */
  free: Document[];
  /** Есть ли у книги основной источник. Второй она не примет, и
   *  предлагать его по умолчанию значит вести человека в отказ. */
  hasPrimary: boolean;
}) {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);

  const [role, setRole] = useState<SourceRole>(hasPrimary ? "visual_reference" : "primary_text");
  const [file, setFile] = useState<File | null>(null);
  const [percent, setPercent] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [over, setOver] = useState(false);

  const [attached, attach, attaching] = useActionState(attachSource, EMPTY);

  function choose(chosen: File | null): void {
    setError(null);

    if (chosen !== null && chosen.size > MAX_BYTES) {
      setError(`Файл больше ${MAX_BYTES / (1024 * 1024)} МБ — столько мы не принимаем`);
      setFile(null);
      return;
    }

    setFile(chosen);
  }

  function send(): void {
    if (file === null) {
      return;
    }

    setError(null);
    setPercent(0);

    const body = new FormData();
    body.append("file", file);
    // Книга и роль уходят той же формой: обработчик витрины пересылает
    // тело в API как есть, не разбирая его.
    body.append("book_id", bookId);
    body.append("source_role", role);

    const request = new XMLHttpRequest();
    request.open("POST", `/api/documents/upload?project=${encodeURIComponent(projectId)}`);

    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        setPercent(Math.round((event.loaded * 100) / event.total));
      }
    });

    request.addEventListener("load", () => {
      setPercent(null);

      let answer: Answer = {};

      try {
        answer = JSON.parse(request.responseText) as Answer;
      } catch {
        // Ответ без JSON — например от прокси. Ниже сработает общий текст.
      }

      // 200 вместо 201 — этот файл в проект уже загружали, и API отдал
      // заведённый документ вместо копии. В комплект он при этом включён:
      // для книги это такая же удача.
      if (request.status === 201 || request.status === 200) {
        setFile(null);

        if (input.current !== null) {
          input.current.value = "";
        }

        // Загрузка прошла мимо серверного действия — обработчиком
        // маршрута, — и сама по себе ничего не обновляет.
        router.refresh();
        return;
      }

      setError(answer.detail ?? `Не получилось загрузить (ошибка ${request.status})`);
    });

    request.addEventListener("error", () => {
      setPercent(null);
      setError("Связь оборвалась. Попробуйте ещё раз.");
    });

    request.send(body);
  }

  const busy = percent !== null;

  return (
    <section className="tile wk-upload">
      <div className="tile__head">
        <h3>Добавить источник</h3>
        <span className="tile__note">PDF, DOCX, EPUB, HTML, Markdown, текст — до 50 МБ</span>
      </div>

      <div
        className={over ? "wk-drop is-over" : "wk-drop"}
        onDragOver={(event) => {
          event.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(event) => {
          event.preventDefault();
          setOver(false);
          choose(event.dataTransfer.files[0] ?? null);
        }}
      >
        <span className="wk-drop__mark" aria-hidden="true">
          📄
        </span>

        {file === null ? (
          <p>
            Перетащите файл сюда или{" "}
            <button
              className="wk-link"
              type="button"
              onClick={() => input.current?.click()}
              disabled={busy}
            >
              выберите на диске
            </button>
          </p>
        ) : (
          <p>
            <b>{file.name}</b>
            <span className="tile__note"> · {fileSize(file.size)}</span>
          </p>
        )}

        <input
          ref={input}
          className="wk-file"
          type="file"
          accept={ACCEPT}
          onChange={(event) => choose(event.target.files?.[0] ?? null)}
        />
      </div>

      <div className="wk-upload__row">
        <label className="field">
          <span>Роль в комплекте</span>
          <select
            value={role}
            disabled={busy}
            onChange={(event) => setRole(event.target.value as SourceRole)}
          >
            {ROLES.map((item) => (
              <option key={item} value={item}>
                {SOURCE_ROLE_LABEL[item]}
              </option>
            ))}
          </select>
          <small>{SOURCE_ROLE_HINT[role]}</small>
        </label>

        <button
          className="btn btn--primary"
          type="button"
          onClick={send}
          disabled={busy || file === null}
        >
          {busy ? "Отправляем…" : "Загрузить в комплект"}
        </button>
      </div>

      {percent !== null && (
        <div className="wk-progress">
          <div className="bar">
            <i style={{ width: `${percent}%` }} />
          </div>
          <span className="tile__note">{percent}%</span>
        </div>
      )}

      <ReportError error={error} />

      {free.length > 0 && (
        <form action={attach} className="bk-free">
          <input type="hidden" name="book_id" value={bookId} />

          <p className="tile__note">
            Либо включите файл, загруженный в проект раньше — он пока не входит ни в одну книгу:
          </p>

          <div className="wk-upload__row">
            <label className="field">
              <span>Загруженный файл</span>
              <select name="document_id" defaultValue={free[0]?.id}>
                {free.map((document) => (
                  <option key={document.id} value={document.id}>
                    {document.title} (
                    {FORMAT_LABEL[document.source_format] ?? document.source_format},{" "}
                    {fileSize(document.size_bytes)})
                  </option>
                ))}
              </select>
            </label>

            <label className="field">
              <span>Роль в комплекте</span>
              <select name="role" defaultValue="visual_reference">
                {ROLES.map((item) => (
                  <option key={item} value={item}>
                    {SOURCE_ROLE_LABEL[item]}
                  </option>
                ))}
              </select>
            </label>

            <button className="btn btn--ghost" type="submit" disabled={attaching}>
              {attaching ? "Включаем…" : "Включить в комплект"}
            </button>
          </div>

          <ReportError error={attached.error} at={attached} />
        </form>
      )}
    </section>
  );
}
