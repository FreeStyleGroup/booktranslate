"use client";

/* Очередь замечаний — рабочее место редактора.

   Устройство экрана следует из одного наблюдения: редактор не читает книгу
   подряд, он разбирает список мест, где проверки что-то нашли. Поэтому
   очередь — это всегда её начало: полсотни худших сегментов. Разобранное
   уходит из неё само, и на его место поднимается следующее. Листать очередь
   постранично было бы враньём: правка меняет оценку сегмента и его место в
   порядке, и «страница 2» после десяти правок показала бы не то, что на ней
   было.

   Строки не исчезают под курсором. Принятое и поправленное остаётся на
   месте, помеченным, до явного «Дальше по очереди»: список, который
   перестраивается после каждого нажатия, невозможно разбирать — глаз теряет
   место, а следующая кнопка оказывается под пальцем уже от другой строки.

   🔥 Все изменения состояния идут от предыдущего значения, а не от
   замыкания обработчика. На соседнем экране это уже стоило потерянных
   решений: два нажатия подряд, до перерисовки, затирали друг друга. */

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";

import type { Finding, Segment } from "../../lib/work";
import { CHECK_CHIP, CHECK_LABEL, KIND_ONE, plural, thousands } from "../labels";
import {
  approveClean,
  approveSegment,
  editSegment,
  reopenSegment,
} from "./actions";

/** Что произошло со строкой на этой странице. */
type Local = {
  // Текст в поле правки, если человек его трогал.
  draft?: string;
  // Состояние сегмента после действия: новый текст, статус и находки.
  now?: Segment;
  // Сколько повторов подтянулось за последней правкой.
  propagated?: number;
  busy?: boolean;
  error?: string;
};

export function QueueBoard({ segments }: { segments: Segment[] }) {
  const router = useRouter();
  const [local, setLocal] = useState<Record<string, Local>>({});

  function patch(id: string, change: Local): void {
    setLocal((was) => ({ ...was, [id]: { ...was[id], ...change } }));
  }

  /* Сколько строк разобрано на этой странице. Считается по действиям, а не
     по состояниям с сервера: сервер про них ещё не спрашивали. */
  const handled = segments.filter((segment) => local[segment.id]?.now !== undefined).length;

  return (
    <>
      <div className="qu-list">
        {segments.map((segment) => (
          <Row
            key={segment.id}
            segment={segment}
            local={local[segment.id] ?? {}}
            patch={patch}
          />
        ))}
      </div>

      {/* Полоса внизу прилипает к экрану: очередь длинная, и уходить за
          кнопкой в самый конец, разобрав пять строк, незачем. */}
      <div className="qu-bar">
        <span>
          {handled === 0
            ? `В очереди ${thousands(segments.length)} ${plural(
                segments.length,
                "сегмент",
                "сегмента",
                "сегментов",
              )}`
            : `Разобрано ${thousands(handled)} из ${thousands(segments.length)}`}
        </span>

        <button
          className="btn btn--ghost btn--small"
          type="button"
          onClick={() => router.refresh()}
        >
          Дальше по очереди
        </button>
      </div>
    </>
  );
}

function Row({
  segment,
  local,
  patch,
}: {
  segment: Segment;
  local: Local;
  patch: (id: string, change: Local) => void;
}) {
  const field = useRef<HTMLTextAreaElement | null>(null);

  // Текущее состояние строки: ответ сервера, если действие уже было, иначе
  // то, что пришло со страницей.
  const live = local.now ?? segment;
  const findings: Finding[] = live.quality?.findings ?? [];
  const text = local.draft ?? live.target_text ?? "";
  const changed = text.trim() !== (live.target_text ?? "").trim();
  const approved = live.status === "approved";

  async function save(): Promise<void> {
    patch(segment.id, { busy: true, error: undefined });

    const answer = await editSegment(segment.id, text);

    if (answer.error !== undefined || answer.saved === undefined) {
      patch(segment.id, { busy: false, error: answer.error ?? "Правка не записалась" });
      return;
    }

    patch(segment.id, {
      busy: false,
      now: answer.saved.segment,
      propagated: answer.saved.propagated,
      // Черновик снят: записанное и есть текущий текст, и держать поверх
      // него копию значило бы показывать «поправлено» на уже сохранённом.
      draft: undefined,
    });
  }

  async function decide(accept: boolean): Promise<void> {
    patch(segment.id, { busy: true, error: undefined });

    const answer = accept
      ? await approveSegment(segment.id)
      : await reopenSegment(segment.id);

    if (answer.error !== undefined || answer.segment === undefined) {
      patch(segment.id, { busy: false, error: answer.error ?? "Не получилось" });
      return;
    }

    patch(segment.id, { busy: false, now: answer.segment, propagated: undefined });
  }

  return (
    <article className={approved ? "qu-row is-done" : "qu-row"}>
      <header className="qu-row__top">
        <span className="qu-row__no">№&nbsp;{segment.position + 1}</span>
        <span className="qu-row__kind">{KIND_ONE[segment.kind] ?? segment.kind}</span>

        <span className="qu-row__chips">
          {findings.map((finding, index) => (
            <span
              className={CHECK_CHIP[finding.check] ?? "chip chip--warn"}
              key={`${finding.check}-${index}`}
            >
              {CHECK_LABEL[finding.check] ?? finding.check}
            </span>
          ))}
          {approved && <span className="chip chip--ok">Принято</span>}
        </span>
      </header>

      <p className="qu-src">{segment.source_text}</p>

      <textarea
        className="qu-dst"
        ref={(element) => {
          field.current = element;

          if (element !== null) {
            fit(element);
          }
        }}
        value={text}
        disabled={local.busy === true}
        maxLength={20000}
        spellCheck
        placeholder="Перевода нет — напишите его здесь"
        onChange={(event) => {
          fit(event.currentTarget);
          patch(segment.id, { draft: event.currentTarget.value });
        }}
        onKeyDown={(event) => {
          // Сочетание для работы вслепую: правка, сохранение, следующая
          // строка — без ухода к мыши на каждой из полусотни.
          if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && changed) {
            event.preventDefault();
            void save();
          }
        }}
      />

      {findings.length > 0 && (
        <ul className="qu-says">
          {findings.map((finding, index) => (
            <li key={`${finding.check}-${index}`}>
              <b>{CHECK_LABEL[finding.check] ?? finding.check}</b>
              {finding.message}
            </li>
          ))}
        </ul>
      )}

      {local.now !== undefined && local.error === undefined && (
        <p className="qu-said" role="status">
          <Outcome segment={local.now} propagated={local.propagated} />
        </p>
      )}

      {local.error !== undefined && (
        <p className="form__error" role="alert">
          {local.error}
        </p>
      )}

      <div className="qu-row__foot">
        <button
          className="btn btn--primary btn--small"
          type="button"
          disabled={local.busy === true || !changed}
          onClick={() => void save()}
        >
          {local.busy === true ? "Записываем…" : "Сохранить правку"}
        </button>

        {approved ? (
          <button
            className="btn btn--ghost btn--small"
            type="button"
            disabled={local.busy === true}
            onClick={() => void decide(false)}
          >
            Вернуть в работу
          </button>
        ) : (
          <button
            className="btn btn--ghost btn--small"
            type="button"
            disabled={local.busy === true || (live.target_text ?? "").trim() === ""}
            onClick={() => void decide(true)}
          >
            Принять
          </button>
        )}
      </div>
    </article>
  );
}

/** Чем кончилось действие — словами, а не значком.
 *
 * Важны два разных исхода правки: замечаний не осталось и замечания
 * остались. Второе не ошибка — проверки могли зацепиться за другое, — но
 * молча показать «сохранено» значило бы сказать, что дело закрыто.
 */
function Outcome({ segment, propagated }: { segment: Segment; propagated?: number }) {
  const left = (segment.quality?.findings ?? []).length;
  const repeats =
    propagated !== undefined && propagated > 0
      ? ` Тот же текст подтянулся ещё в ${thousands(propagated)} ${plural(
          propagated,
          "сегменте",
          "сегментах",
          "сегментах",
        )} книги.`
      : "";

  if (segment.status === "approved") {
    return (
      <>
        <span aria-hidden="true">✅</span> Принято — сегмент закрыт.
        {left > 0 && " Находки остались видны: понятно, что было замечено и всё-таки принято."}
      </>
    );
  }

  if (left === 0) {
    return (
      <>
        <span aria-hidden="true">✅</span> Записано, замечаний не осталось.{repeats} Осталось
        принять.
      </>
    );
  }

  return (
    <>
      <span aria-hidden="true">⚠️</span> Записано, но проверки всё ещё не сходятся — смотрите
      выше.{repeats}
    </>
  );
}

/** Поле правки по высоте текста: перевод бывает и в строку, и в абзац. */
function fit(element: HTMLTextAreaElement): void {
  element.style.height = "auto";
  element.style.height = `${element.scrollHeight}px`;
}

/** Принять всё, к чему у проверок нет претензий.
 *
 * Стоит над очередью, а не в ней: это действие по книге целиком. После
 * него очередь не меняется — помеченное остаётся помеченным, — поэтому
 * страницу здесь обновлять можно: из-под курсора ничего не уедет.
 */
export function ApproveClean({ documentId, clean }: { documentId: string; clean: number }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(): Promise<void> {
    setBusy(true);
    setError(null);

    const answer = await approveClean(documentId);

    setBusy(false);

    if (answer.error !== undefined || answer.approved === undefined) {
      setError(answer.error ?? "Не получилось");
      return;
    }

    setDone(answer.approved);
    router.refresh();
  }

  if (done !== null) {
    return (
      <p className="wk-note" role="status">
        <span aria-hidden="true">✅</span> Принято {thousands(done)}{" "}
        {plural(done, "сегмент", "сегмента", "сегментов")} без замечаний. В очереди осталось
        только спорное.
      </p>
    );
  }

  return (
    <>
      <button
        className="btn btn--ghost btn--small"
        type="button"
        disabled={busy || clean === 0}
        onClick={() => void run()}
      >
        {busy ? "Принимаем…" : `Принять чистые (${thousands(clean)})`}
      </button>

      {error !== null && (
        <p className="form__error" role="alert">
          {error}
        </p>
      )}
    </>
  );
}
