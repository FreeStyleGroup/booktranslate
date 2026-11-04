"use server";

/* Действия автоматического режима. Что можно, решает API; значения сверяются здесь, потому что серверное
   действие вызывается и в обход отрисованной страницы. */

import { revalidatePath } from "next/cache";

import { ApiError, apiFetch } from "../../lib/api";
import { accessToken, organizationId } from "../../lib/session";

export type AutopilotResult = { error?: string; done?: boolean };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DAMAGED = "Запрос повреждён — обновите страницу";

function failure(error: unknown): AutopilotResult {
  if (error instanceof ApiError) {
    return { error: error.message };
  }

  return { error: "Сервис недоступен. Попробуйте ещё раз." };
}

async function send(path: string, body: unknown): Promise<void> {
  const token = await accessToken();

  if (token === undefined) {
    throw new ApiError(401, "Сеанс закончился — войдите заново");
  }

  await apiFetch(path, { method: "POST", token, organizationId: await organizationId(), body });
}

function budgetOf(value: string): number | null | "bad" {
  const clean = value.trim().replace(",", ".");

  if (clean === "") {
    return null;
  }

  const parsed = Number(clean);

  return Number.isFinite(parsed) && parsed > 0 ? parsed : "bad";
}

export async function startAutopilot(
  bookId: string,
  semantic: boolean,
  budget: string,
): Promise<AutopilotResult> {
  if (!UUID.test(bookId)) {
    return { error: DAMAGED };
  }

  const budgetUsd = budgetOf(budget);

  if (budgetUsd === "bad") {
    return { error: "Предел сметы — положительное число" };
  }

  try {
    await send(`/books/${bookId}/autopilot`, {
      semantic: semantic === true,
      budget_usd: budgetUsd,
    });
    revalidatePath(`/app/books/${bookId}`);

    return { done: true };
  } catch (error) {
    return failure(error);
  }
}

export async function resumeAutopilot(
  bookId: string,
  runId: string,
  budget: string,
): Promise<AutopilotResult> {
  if (!UUID.test(bookId) || !UUID.test(runId)) {
    return { error: DAMAGED };
  }

  const budgetUsd = budgetOf(budget);

  if (budgetUsd === "bad") {
    return { error: "Предел сметы — положительное число" };
  }

  try {
    await send(`/autopilot-runs/${runId}/resume`, { budget_usd: budgetUsd });
    revalidatePath(`/app/books/${bookId}`);

    return { done: true };
  } catch (error) {
    return failure(error);
  }
}

export async function cancelAutopilot(bookId: string, runId: string): Promise<AutopilotResult> {
  if (!UUID.test(bookId) || !UUID.test(runId)) {
    return { error: DAMAGED };
  }

  try {
    await send(`/autopilot-runs/${runId}/cancel`, undefined);
    revalidatePath(`/app/books/${bookId}`);

    return { done: true };
  } catch (error) {
    return failure(error);
  }
}
