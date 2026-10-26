/* Вкладка объектов одного вида: рисунки, таблицы, формулы или код.

   Рисунки — карточками с оригиналом: их сверяют глазами. Остальное —
   таблицей с кодом объекта отдельным столбцом, как у блоков: по коду
   объект называют в переписке и находят из любого места книги. */

import Link from "next/link";

import type { BookObject } from "../../../../../lib/work";
import { plural, thousands } from "../../../../labels";
import { CopyId } from "../../../../ui/copy-id";
import { DataTable, type Column } from "../../../../ui/table";
import { FigureImages, Formula } from "./object-views";

export function ObjectsTab({
  type,
  title,
  objects,
  cardPath,
  empty,
}: {
  type: string;
  title: string;
  objects: BookObject[];
  /** Адрес карточки объекта без его идентификатора. */
  cardPath: string;
  empty: string;
}) {
  const card = (item: BookObject) => `${cardPath}/${item.id}`;

  if (type === "figure") {
    return objects.length === 0 ? (
      <p className="tile__empty">{empty}</p>
    ) : (
      <ul className="bk-figures">
        {objects.map((item) => (
          <li key={item.id} id={item.code} className="bk-figures__item">
            <Link href={card(item)} className="bk-figures__picture">
              <FigureImages object={item} />
            </Link>
            <div className="bk-figures__meta">
              <ObjectId item={item} href={card(item)} />
              <p className="bk-block-text">{item.caption ?? "Без подписи"}</p>
              <Mentions item={item} />
            </div>
          </li>
        ))}
      </ul>
    );
  }

  return (
    <DataTable
      caption={title}
      columns={columns(type, card)}
      rows={objects}
      rowAnchor={(item) => item.code}
      empty={empty}
    />
  );
}

function columns(type: string, card: (item: BookObject) => string): Column<BookObject>[] {
  const id: Column<BookObject> = {
    title: "Object ID",
    cell: (item) => <ObjectId item={item} href={card(item)} />,
  };
  const caption: Column<BookObject> = {
    title: "Подпись",
    cell: (item) => <span className="bk-block-text">{item.caption ?? "—"}</span>,
  };
  const mentions: Column<BookObject> = {
    title: "Упоминаний",
    numeric: true,
    secondary: true,
    cell: (item) => <span className="tile__note">{thousands(item.references)}</span>,
  };

  if (type === "table") {
    return [
      id,
      caption,
      {
        title: "Сетка",
        secondary: true,
        cell: (item) => (
          <span className="tile__note">
            {item.payload.rows ?? 0} × {item.payload.cols ?? 0},{" "}
            {plural(item.content_codes.length, "ячейка", "ячейки", "ячеек")} с текстом
          </span>
        ),
      },
      mentions,
    ];
  }

  if (type === "equation") {
    return [
      id,
      { title: "Формула", cell: (item) => <Formula payload={item.payload} /> },
      {
        title: "Номер",
        secondary: true,
        cell: (item) => <span className="tile__note">{item.label ?? "—"}</span>,
      },
      mentions,
    ];
  }

  return [
    id,
    caption,
    {
      title: "Язык",
      secondary: true,
      cell: (item) => <span className="tile__note">{item.payload.language ?? "не указан"}</span>,
    },
    mentions,
  ];
}

function ObjectId({ item, href }: { item: BookObject; href: string }) {
  return (
    <span className="bk-block-id">
      <CopyId value={item.full_code} title="код объекта" />
      <Link className="tile__note" href={href}>
        {item.label !== null ? `№ ${item.label} · ` : ""}открыть
      </Link>
    </span>
  );
}

function Mentions({ item }: { item: BookObject }) {
  return (
    <p className="tile__note">
      {item.references === 0
        ? "В тексте не упоминается"
        : `Упоминаний в тексте: ${thousands(item.references)}`}
      {item.before_code !== null ? ` · стоит перед ${item.before_code}` : " · в конце главы"}
    </p>
  );
}

