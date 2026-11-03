/* Сравнение двух текстов по словам: что убрано, что добавлено. */

import type { RevisionChange } from "../../lib/work";

export function RevisionDiff({ items }: { items: RevisionChange[] }) {
  return (
    <p className="bk-diff">
      {items.map((item, index) =>
        item.op === "insert" ? (
          <ins key={index}>{item.text}</ins>
        ) : item.op === "delete" ? (
          <del key={index}>{item.text}</del>
        ) : (
          <span key={index}>{item.text}</span>
        ),
      )}
    </p>
  );
}
