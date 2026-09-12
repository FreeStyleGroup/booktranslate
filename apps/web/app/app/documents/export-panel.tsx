"use client";

/* Выгрузка перевода: выбор формата и скачивание.

   Файл забирается запросом со страницы, а не ссылкой. У ссылки два изъяна,
   и оба видны на большой книге. Пока API вписывает перевод в DOCX на
   восемьсот страниц, проходят секунды, и у ссылки в это время нет никакого
   состояния — человек нажимает второй раз. А отказ — «не переведено
   блоков: 40» — ссылка показала бы страницей с JSON вместо книги. Запрос
   даёт и «собираем…», и отказ рядом с кнопкой, и число блоков, ушедших
   исходным текстом, — оно приходит заголовком.

   Форматы приходят вместе с документом: какие из них есть, знает реестр
   сборщиков в API, и рисовать кнопку по своему списку значило бы однажды
   пообещать формат, которого нет. */

import { useState, type ReactNode } from "react";

import type { ExportFormat } from "../../lib/work";
import { FORMAT_LABEL, plural, thousands } from "../labels";

// Что за формат — словами, по которым выбирают. Формат оригинала
// подписывается именем исходника: «DOCX — как оригинал», а не «source».
const ABOUT: Record<ExportFormat, { title: (source: string) => string; hint: string }> = {
  source: {
    title: (source) => `${source} — как оригинал`,
    hint: "Перевод вписан в исходный файл: стили, картинки, таблицы и оглавление на месте.",
  },
  docx: {
    title: () => "DOCX — новый документ",
    hint: "Заголовки, абзацы и списки стилями Word. Оформление и картинки исходника не переносятся, зато файл правится где угодно.",
  },
  markdown: {
    title: () => "Markdown",
    hint: "Структура разметкой: заголовки, списки, предупреждения. Удобно вычитывать в редакторе.",
  },
  text: {
    title: () => "Текст",
    hint: "Абзацы через пустую строку, без оформления.",
  },
};

export function ExportPanel({
  documentId,
  sourceFormat,
  formats,
  untranslated,
  title,
  lead,
  actions,
}: {
  documentId: string;
  sourceFormat: string;
  formats: ExportFormat[];
  // Сегментов без перевода. Ноль — книга целиком; иначе — черновик, и
  // человек обязан это видеть до нажатия, а не после.
  untranslated: number;
  // У переведённой книги панель и есть её итог: заголовок «Книга
  // переведена», слова о замечаниях и ссылка на очередь стоят здесь же,
  // а не в соседней карточке с второй кнопкой «Скачать».
  title?: string;
  lead?: string;
  actions?: ReactNode;
}) {
  const [format, setFormat] = useState<ExportFormat>(formats[0] ?? "text");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<{ name: string; untranslated: number } | null>(null);

  const draft = untranslated > 0;
  const source = FORMAT_LABEL[sourceFormat] ?? sourceFormat.toUpperCase();

  async function download(): Promise<void> {
    setBusy(true);
    setError(null);
    setSaved(null);

    const query = new URLSearchParams({ format });

    if (draft) {
      query.set("draft", "1");
    }

    let response: Response;

    try {
      response = await fetch(`/api/documents/${documentId}/export?${query}`);
    } catch {
      setBusy(false);
      setError("Сервис недоступен");
      return;
    }

    if (!response.ok) {
      setBusy(false);
      setError(await failure(response));
      return;
    }

    const name = attachmentName(response.headers.get("content-disposition")) ?? `перевод.${format}`;
    const blocks = Number(response.headers.get("x-untranslated-blocks") ?? "0");

    save(await response.blob(), name);

    setBusy(false);
    setSaved({ name, untranslated: Number.isFinite(blocks) ? blocks : 0 });
  }

  return (
    <section className="tile ex" id="export">
      <div className="tile__head">
        <h3>{title ?? "Забрать перевод"}</h3>
        <span className="tile__note">{draft ? "черновик" : "книга целиком"}</span>
      </div>

      {lead !== undefined && <p className="ex-lead">{lead}</p>}

      <div className="ex-formats" role="radiogroup" aria-label="Формат файла">
        {formats.map((option) => (
          <label className={"ex-format" + (option === format ? " is-active" : "")} key={option}>
            <input
              type="radio"
              name="format"
              value={option}
              checked={option === format}
              onChange={() => setFormat(option)}
            />
            <b>{ABOUT[option].title(source)}</b>
            <span>{ABOUT[option].hint}</span>
          </label>
        ))}
      </div>

      {draft && (
        <p className="wk-note ex-draft" role="status">
          <span aria-hidden="true">✋</span>
          <span>
            Переведено не всё: {thousands(untranslated)}{" "}
            {plural(untranslated, "сегмент уйдёт", "сегмента уйдут", "сегментов уйдут")} в файл
            исходным текстом. Это черновик — показать середину работы или отдать главу на вычитку, а
            не сдавать заказчику.
          </span>
        </p>
      )}

      {error !== null && (
        <p className="form__error" role="alert">
          {error}
        </p>
      )}

      {saved !== null && (
        <p className="tile__note ex-saved" role="status">
          Файл собран: <b>{saved.name}</b>
          {saved.untranslated > 0 &&
            ` · ${thousands(saved.untranslated)} ${plural(
              saved.untranslated,
              "блок",
              "блока",
              "блоков",
            )} исходным текстом`}
        </p>
      )}

      <div className="tile__foot">
        <button
          className="btn btn--primary btn--small"
          type="button"
          disabled={busy}
          onClick={() => void download()}
        >
          {busy ? "Собираем файл…" : draft ? "Скачать черновик" : "Скачать перевод"}
        </button>
        {actions}
      </div>

      {/* Что теряется — зависит от формата: по месту теряется только
          оформление внутри абзаца, в новом файле — всё оформление исходника. */}
      <p className="tile__note wk-seg__foot">
        {format === "source"
          ? "Оформление внутри абзаца — полужирное слово, ссылка на трёх словах — в переводе не сохраняется: сегмент хранит текст, а не разметку. Всё остальное на месте: стиль абзаца, картинки, сноски, таблицы и оглавление."
          : "В новый файл переносится структура: заголовки, абзацы, пункты списков, подписи и предупреждения. Оформление, картинки и таблицы исходника — нет."}
      </p>
    </section>
  );
}

/** Причина отказа из ответа витрины. */
async function failure(response: Response): Promise<string> {
  try {
    const payload: unknown = await response.json();

    if (typeof payload === "object" && payload !== null && "error" in payload) {
      const error = (payload as { error: unknown }).error;

      if (typeof error === "string") {
        return error;
      }
    }
  } catch {
    // Ответ без JSON — например от прокси. Ниже вернётся общий текст.
  }

  return `Сервер ответил ошибкой ${response.status}`;
}

/** Имя файла из Content-Disposition.
 *
 * API отдаёт его в форме `filename*=UTF-8''…` с процентным кодированием:
 * имя собирается из названия книги, а оно бывает русским, и в обычный
 * `filename` за пределы latin-1 выходить нельзя.
 */
function attachmentName(header: string | null): string | null {
  if (header === null) {
    return null;
  }

  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(header);

  if (encoded !== null) {
    try {
      return decodeURIComponent(encoded[1]);
    } catch {
      // Битое кодирование — имя ниже возьмётся из простого filename.
    }
  }

  const plain = /filename="?([^";]+)"?/i.exec(header);

  return plain === null ? null : plain[1];
}

/** Отдать файл браузеру под нужным именем. */
function save(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");

  link.href = url;
  link.download = name;
  link.click();

  // Адрес освобождается следующим ходом, а не сразу: Firefox начинает
  // скачивание асинхронно, и отозванный тут же адрес обрывал бы его.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
