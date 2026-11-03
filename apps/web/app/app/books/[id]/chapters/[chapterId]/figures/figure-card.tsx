"use client";

/* Сверка рисунка: оригинал рядом с переводом, надписи под ними.

   Ключ карточки — версия перевода: новая перерисовка сбрасывает форму. Предупреждение о сомнениях
   сервиса видно до кнопки: такой рисунок сервис сам не утвердит и в автоматическом режиме. */

import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";

import type { ChapterFigures, FigureImage, FigureRegion } from "../../../../../../lib/work";
import { FIGURE_STATUS_CHIP, FIGURE_STATUS_LABEL, thousands } from "../../../../../labels";
import { CopyId } from "../../../../../ui/copy-id";
import { ReportError, useToast } from "../../../../../ui/toast";
import {
  approveFigure,
  keepFigureOriginal,
  saveRegions,
  translateFigures,
  type FigureResult,
} from "../../../../figure-actions";

const POLL_MS = 4000;

const ORIGIN_LABEL: Record<string, string> = {
  model: "модель",
  memory: "память переводов",
  glossary: "глоссарий",
  copy: "без перевода",
  human: "человек",
};

function useAct(): {
  pending: boolean;
  error: string | null;
  act: (action: () => Promise<FigureResult>, done: string) => void;
} {
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const router = useRouter();
  const toast = useToast();

  function act(action: () => Promise<FigureResult>, done: string): void {
    setError(null);

    start(async () => {
      const result = await action();

      if (result.error !== undefined) {
        setError(result.error);
        router.refresh();
        return;
      }

      toast.ok(done);
      router.refresh();
    });
  }

  return { pending, error, act };
}

export function FiguresHead({
  bookId,
  chapterId,
  state,
  canWork,
}: {
  bookId: string;
  chapterId: string;
  state: ChapterFigures;
  canWork: boolean;
}) {
  const { pending, error, act } = useAct();
  const router = useRouter();
  const running = state.job_state === "waiting" || state.job_state === "running";
  const unread = state.images.filter((item) => item.current === null).length;

  useEffect(() => {
    if (!running) {
      return;
    }

    const timer = window.setInterval(() => router.refresh(), POLL_MS);

    return () => window.clearInterval(timer);
  }, [running, router]);

  return (
    <section className="tile">
      <div className="tile__head">
        <h3>Чтение надписей</h3>
        {running && <span className="chip chip--info">идёт</span>}
      </div>

      <p className="tile__note">
        Сервис находит надписи, переводит их через глоссарий и память и рисует перевод поверх копии.
        Оригинал не меняется. Что сервис прочитал неуверенно, он так и помечает: решает человек.
      </p>

      {state.job_state === "failed" && state.job_error !== null && (
        <p className="bk-mismatch" role="status">
          <span aria-hidden="true">⚠</span>
          <span>Сорвалось: {state.job_error}</span>
        </p>
      )}

      {canWork && !running && unread > 0 && (
        <div className="wk-actions">
          <button
            className="btn btn--primary"
            type="button"
            disabled={pending}
            onClick={() =>
              act(() => translateFigures(bookId, chapterId), "Рисунки поставлены в очередь")
            }
          >
            Прочитать и перевести: {thousands(unread)}
          </button>
        </div>
      )}

      <ReportError error={error} />
    </section>
  );
}

export function FigureCard({
  bookId,
  chapterId,
  image,
  canWork,
  canDecide,
}: {
  bookId: string;
  chapterId: string;
  image: FigureImage;
  canWork: boolean;
  canDecide: boolean;
}) {
  const current = image.current;
  const [regions, setRegions] = useState<FigureRegion[]>(current?.regions ?? []);
  const { pending, error, act } = useAct();

  const isDraft = current?.status === "draft";
  const changed = JSON.stringify(regions) !== JSON.stringify(current?.regions ?? []);
  const complete = regions.every((item) => (item.target_text ?? "").trim() !== "");

  function update(id: string, change: Partial<FigureRegion>): void {
    setRegions((before) =>
      before.map((item) => (item.id === id ? { ...item, ...change } : item)),
    );
  }

  return (
    <section className="tile">
      <div className="tile__head">
        <h3 className="bk-review__code">
          <CopyId value={image.code} title="код рисунка" />
        </h3>
        {current === null ? (
          <span className="chip chip--info">не прочитан</span>
        ) : (
          <span className={FIGURE_STATUS_CHIP[current.status]}>
            {FIGURE_STATUS_LABEL[current.status]}
          </span>
        )}
      </div>

      {current?.needs_human && isDraft && (
        <p className="bk-mismatch" role="status">
          <span aria-hidden="true">⚠</span>
          <span>
            Нужен человек{current.note !== null ? `: ${current.note}` : ": сервис не уверен в чтении"}
          </span>
        </p>
      )}

      <div className="is-pair bk-review__pair">
        <div>
          <h4>Оригинал</h4>
          {/* Оригинал показывается как есть, без пережатия: сверяют именно его. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            className="bk-figure"
            src={`/api/objects/${image.object_id}/images/${image.index}`}
            alt={`Оригинал рисунка ${image.code}`}
          />
        </div>
        <div>
          <h4>Перевод</h4>
          {current?.has_asset ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              className="bk-figure"
              src={`/api/figure-translations/${current.id}/image`}
              alt={`Перевод рисунка ${image.code}`}
            />
          ) : (
            <p className="tile__note">
              {current?.status === "no_text"
                ? "Надписей нет: переводить нечего."
                : current?.status === "kept_original"
                  ? "Оставлен как в книге."
                  : "Файла с переводом нет."}
            </p>
          )}
        </div>
      </div>

      {regions.length > 0 && (
        <div className="bk-regions">
          {regions.map((item) => (
            <div className="bk-region" key={item.id}>
              <p className="bk-block-text">{item.source_text}</p>
              <label className="field">
                <span>
                  Перевод
                  {item.origin !== null && ` · ${ORIGIN_LABEL[item.origin] ?? item.origin}`}
                  {item.confidence < 0.8 && " · прочитано неуверенно"}
                  {item.overflow && " · не помещается"}
                </span>
                <input
                  type="text"
                  value={item.target_text ?? ""}
                  maxLength={500}
                  disabled={!canWork || !isDraft || pending}
                  onChange={(event) => update(item.id, { target_text: event.target.value })}
                />
              </label>
              <div className="bk-region__box">
                {(["x", "y", "w", "h"] as const).map((axis) => (
                  <label className="field" key={axis}>
                    <span>{{ x: "слева", y: "сверху", w: "ширина", h: "высота" }[axis]}</span>
                    <input
                      type="number"
                      min={axis === "w" || axis === "h" ? 1 : 0}
                      max={100000}
                      value={item[axis]}
                      disabled={!canWork || !isDraft || pending}
                      onChange={(event) => update(item.id, { [axis]: Number(event.target.value) })}
                    />
                  </label>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="wk-actions">
        {canWork && isDraft && current !== null && (
          <button
            className={changed ? "btn btn--primary" : "btn btn--ghost"}
            type="button"
            disabled={pending || !changed || !complete}
            title={complete ? undefined : "У каждой надписи должен быть перевод"}
            onClick={() =>
              act(
                () =>
                  saveRegions(
                    bookId,
                    chapterId,
                    current.id,
                    regions.map((item) => ({
                      id: item.id,
                      x: item.x,
                      y: item.y,
                      w: item.w,
                      h: item.h,
                      source_text: item.source_text,
                      target_text: item.target_text ?? "",
                    })),
                  ),
                "Правки сохранены: рисунок перерисован",
              )
            }
          >
            Сохранить правки
          </button>
        )}
        {canDecide && isDraft && current !== null && current.has_asset && (
          <button
            className="btn btn--primary"
            type="button"
            disabled={pending || changed}
            title={changed ? "Сначала сохраните правки" : undefined}
            onClick={() =>
              act(() => approveFigure(bookId, chapterId, current.id), "Перевод рисунка утверждён")
            }
          >
            Утвердить перевод
          </button>
        )}
        {canDecide && current?.status !== "kept_original" && current?.status !== "approved" && (
          <button
            className="btn btn--ghost"
            type="button"
            disabled={pending}
            onClick={() =>
              act(
                () => keepFigureOriginal(bookId, chapterId, image.object_id, image.index),
                "Рисунок оставлен как в книге",
              )
            }
          >
            Оставить как в книге
          </button>
        )}
      </div>

      <ReportError error={error} />
    </section>
  );
}
