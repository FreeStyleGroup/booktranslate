"use client";

/* Загрузка книги.

   Обычным запросом с показом хода отправки, а не серверным действием:
   книга — это десятки мегабайт, а действие принимает тело целиком в память
   и ограничено мегабайтом. Почему именно так, подробно — в
   `app/api/documents/upload/route.ts`.

   Полоса хода здесь не украшение. Файл на тридцать мегабайт по обычному
   каналу уходит полминуты, и без полосы человек не отличает медленную
   отправку от зависшей: жмёт ещё раз, и на сервер едут две копии.

   Ход отправки показывает только XMLHttpRequest: у fetch его нет вовсе —
   он сообщает о ходе приёма ответа, но не отправки запроса. */

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import type { Project } from "../../lib/work";
import { fileSize } from "../labels";

// Согласовано с потолком прокси и API (deploy/Caddyfile, MAX_UPLOAD_MB).
// Здесь — чтобы сказать «файл слишком большой» до отправки, а не после
// тридцати мегабайт и отказа.
const MAX_BYTES = 50 * 1024 * 1024;

// Что предлагать в окне выбора файла. XLIFF принимается API, но пока не
// разбирается, поэтому и не предлагается: файл, который примут и не
// смогут открыть, — обещание, которого мы не сдержим. PDF — только с
// текстовым слоем; скан разбор назовёт сканом.
const ACCEPT = ".pdf,.docx,.epub,.html,.htm,.md,.markdown,.txt";

type Answer = { id?: string; detail?: string; title?: string };

export function Upload({ projects, current }: { projects: Project[]; current?: string }) {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);

  const [project, setProject] = useState(current ?? projects[0]?.id ?? "");
  const [file, setFile] = useState<File | null>(null);
  const [percent, setPercent] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [over, setOver] = useState(false);

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
    if (file === null || project === "") {
      return;
    }

    setError(null);
    setPercent(0);

    const body = new FormData();
    body.append("file", file);

    const request = new XMLHttpRequest();
    request.open("POST", `/api/documents/upload?project=${encodeURIComponent(project)}`);

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

      // 200 вместо 201 — этот файл уже загружали: API отдаёт заведённый
      // документ вместо копии. Ведём на его карточку и помечаем это в
      // адресе — иначе человек будет искать в списке второй такой же и
      // решит, что загрузка не сработала.
      const again = request.status === 200;

      if (request.status === 201 || again) {
        setFile(null);

        if (input.current !== null) {
          input.current.value = "";
        }

        // refresh() вместе с push(): загрузка прошла мимо серверного
        // действия — обработчиком маршрута, — и сама по себе ничего не
        // обновляет. Без него список и счётчики в меню остаются такими,
        // какими были до загрузки.
        router.refresh();

        if (answer.id !== undefined) {
          router.push(`/app/documents/${answer.id}${again ? "?same=1" : ""}`);
        }

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

  if (projects.length === 0) {
    return null;
  }

  return (
    <section className="tile wk-upload">
      <div className="tile__head">
        <h3>Загрузить книгу</h3>
        <span className="tile__note">DOCX, EPUB, HTML, Markdown, текст — до 50 МБ</span>
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
          <span>В проект</span>
          <select
            value={project}
            onChange={(event) => setProject(event.target.value)}
            disabled={busy}
          >
            {projects.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} ({item.source_language} → {item.target_language})
              </option>
            ))}
          </select>
        </label>

        <button
          className="btn btn--primary"
          type="button"
          onClick={send}
          disabled={busy || file === null}
        >
          {busy ? "Отправляем…" : "Загрузить"}
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

      {error !== null && (
        <p className="form__error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
