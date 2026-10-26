/* Как показать оригинал объекта: формулу, таблицу, рисунок.

   Формула строится из дерева MathML элемент за элементом, без вставки
   разметки строкой: теги и атрибуты в дереве — только из закрытого
   перечня API, а текст React экранирует сам. Скрипту из чужой книги
   здесь просто негде оказаться. Браузер рисует MathML сам — библиотека
   для этого не нужна. */

import { createElement, type ReactNode } from "react";

import type { BlockRef, BookObject, MathTree, ObjectPayload } from "../../../../../lib/work";

export function Formula({ payload }: { payload: ObjectPayload }) {
  if (payload.preview) {
    return <span className="bk-formula">{mathNode(payload.preview, "0")}</span>;
  }

  // Формула Word (OMML) браузером не рисуется — показывается её текст.
  return <code className="bk-formula bk-formula--text">{payload.text ?? "—"}</code>;
}

function mathNode(tree: MathTree, key: string): ReactNode {
  const [tag, attributes, ...children] = tree;

  return createElement(
    tag,
    { ...attributes, key },
    ...children.map((child, index) =>
      typeof child === "string" ? child : mathNode(child, `${key}.${index}`),
    ),
  );
}

/** Таблица по сетке: ячейки на своих местах, объединения как в исходнике. */
export function TableGrid({ payload, cells }: { payload: ObjectPayload; cells: BlockRef[] }) {
  const texts = new Map<string, BlockRef[]>();

  for (const cell of cells) {
    if (cell.row === null || cell.column === null) {
      continue;
    }
    const key = `${cell.row}:${cell.column}`;
    texts.set(key, [...(texts.get(key) ?? []), cell]);
  }

  const rows = Array.from({ length: payload.rows ?? 0 }, (_, row) =>
    (payload.cells ?? []).filter((cell) => cell.row === row),
  );

  return (
    <div className="bk-grid-wrap">
      <table className="bk-grid">
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {row.map((cell) => {
                const content = texts.get(`${cell.row}:${cell.col}`) ?? [];
                const Cell = cell.header ? "th" : "td";

                return (
                  <Cell
                    key={`${cell.row}:${cell.col}`}
                    rowSpan={cell.rowspan > 1 ? cell.rowspan : undefined}
                    colSpan={cell.colspan > 1 ? cell.colspan : undefined}
                  >
                    {content.map((block) => (
                      <span key={block.id} className="bk-grid__part" title={block.full_code}>
                        {block.text}
                      </span>
                    ))}
                  </Cell>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Изображения рисунка — оригиналы через витрину. */
export function FigureImages({ object, large = false }: { object: BookObject; large?: boolean }) {
  const images = object.payload.images ?? [];

  return (
    <div className={large ? "bk-figure bk-figure--large" : "bk-figure"}>
      {images.map((image, index) =>
        image.sha256 === null ? (
          <p key={index} className="bk-figure__missing">
            Изображения нет в исходнике{image.src !== null ? `: ${image.src}` : ""}
          </p>
        ) : (
          // Обычный <img>, а не next/image: оригинал показывается как есть,
          // без пережатия, — сверяют именно его.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            key={index}
            src={`/api/objects/${object.id}/images/${index}`}
            alt={image.alt ?? object.caption ?? object.full_code}
            loading="lazy"
          />
        ),
      )}
    </div>
  );
}
