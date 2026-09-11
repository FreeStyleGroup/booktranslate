"use server";

/* Действия терминологического прохода: собрать кандидатов и решить их.

   Решения уходят пачкой, а не по одному, и это не оптимизация: двести
   кандидатов — одна работа человека, и разваливать её на двести запросов
   значит получить наполовину решённый словарь, если связь оборвётся
   посередине. API применяет пачку одной транзакцией. */

import { revalidatePath } from "next/cache";

import { ApiError, apiFetch } from "../../lib/api";
import { accessToken, organizationId } from "../../lib/session";

export type Result = { error?: string; report?: Report };

export type Report = { accepted: number; rejected: number; remaining: number };

/** Решение по одному кандидату — ровно то, что понимает API. */
export type Decision = {
  candidate_id: string;
  accept: boolean;
  target_term?: string;
  kind?: string;
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Разряды словаря — списком, а не любой строкой: серверное действие
// вызывается и в обход отрисованной страницы, и передавать в API что попало
// незачем.
const KINDS = new Set(["term", "abbreviation", "do_not_translate", "notation", "proper_name"]);

// Сколько решений отправлять за раз. Потолок API — 500 на запрос; берём с
// запасом, чтобы пачка оставалась короткой транзакцией.
const BATCH = 200;

function failure(error: unknown): Result {
  if (error instanceof ApiError) {
    return { error: error.message };
  }

  return { error: "Сервис недоступен. Попробуйте ещё раз." };
}

async function credentials(): Promise<{ token: string; organizationId: string | undefined }> {
  const token = await accessToken();

  if (token === undefined) {
    throw new ApiError(401, "Сеанс закончился — войдите заново");
  }

  return { token, organizationId: await organizationId() };
}

/** Пройти по документу и собрать кандидатов в словарь.
 *
 * Повторный проход не сбрасывает работу: принятое и отклонённое остаётся,
 * у нерешённого обновляются частота и пример.
 */
export async function extractTerms(documentId: string, minFrequency: number): Promise<Result> {
  if (!UUID.test(documentId)) {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  // Порог подбирают под книгу: на руководстве в тридцать страниц двойка
  // нормальна, на книге в четыреста её поднимают, иначе список будет
  // длиннее, чем человек разберёт.
  const frequency = Math.min(50, Math.max(1, Math.round(minFrequency)));

  try {
    const { token, organizationId: organization } = await credentials();

    await apiFetch(
      `/documents/${documentId}/terminology/extract?min_frequency=${frequency}&limit=400`,
      { method: "POST", token, organizationId: organization },
    );
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/app/terms");

  return {};
}

export async function decideTerms(documentId: string, decisions: Decision[]): Promise<Result> {
  if (!UUID.test(documentId)) {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  const clean: Decision[] = [];

  for (const decision of decisions) {
    if (!UUID.test(decision.candidate_id)) {
      return { error: "Запрос повреждён — обновите страницу" };
    }

    if (decision.kind !== undefined && !KINDS.has(decision.kind)) {
      return { error: "Неизвестный разряд термина" };
    }

    clean.push({
      candidate_id: decision.candidate_id,
      accept: decision.accept === true,
      // Пустой перевод не отправляем вовсе: у непереводимого он совпадает с
      // исходником, и API подставит его сам.
      target_term: decision.target_term?.trim() || undefined,
      kind: decision.kind,
    });
  }

  if (clean.length === 0) {
    return { error: "Нечего записывать: ни одного решения" };
  }

  let report: Report = { accepted: 0, rejected: 0, remaining: 0 };

  try {
    const { token, organizationId: organization } = await credentials();

    for (let start = 0; start < clean.length; start += BATCH) {
      const answer = await apiFetch<Report>(`/documents/${documentId}/terminology/decisions`, {
        method: "POST",
        token,
        organizationId: organization,
        body: { decisions: clean.slice(start, start + BATCH) },
      });

      // Принятое и отклонённое складываем по пачкам, остаток берём из
      // последнего ответа: он и есть текущее состояние документа.
      report = {
        accepted: report.accepted + answer.accepted,
        rejected: report.rejected + answer.rejected,
        remaining: answer.remaining,
      };
    }
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/app/terms");
  revalidatePath(`/app/documents/${documentId}`);
  revalidatePath("/app");

  return { report };
}
