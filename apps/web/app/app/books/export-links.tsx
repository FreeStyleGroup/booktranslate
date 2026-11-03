/* Ссылки на черновую выгрузку.

   Обычные ссылки на маршруты витрины: файл лежит за токеном, браузер его не видит, и
   выдаёт файл сервер витрины. Форматы приходят от API — там живёт реестр сборщиков. */

import type { ExportFormat } from "../../lib/work";

const LABEL: Record<ExportFormat, string> = {
  source: "В формате оригинала",
  docx: "Word",
  markdown: "Markdown",
  text: "Текст",
};

export function ExportLinks({
  path,
  formats,
  draft,
}: {
  path: string;
  formats: ExportFormat[];
  /** Есть непереведённое: оно уйдёт исходным текстом, и сказать об этом надо до нажатия. */
  draft: boolean;
}) {
  return (
    <>
      <div className="wk-actions">
        {formats.map((format) => (
          <a
            key={format}
            className="btn btn--ghost btn--small"
            href={`${path}?format=${format}${draft ? "&draft=1" : ""}`}
            download
          >
            {LABEL[format]}
          </a>
        ))}
      </div>
      {draft && (
        <p className="tile__note">
          Переведено не всё: непереведённые блоки уйдут в файл исходным текстом.
        </p>
      )}
    </>
  );
}
