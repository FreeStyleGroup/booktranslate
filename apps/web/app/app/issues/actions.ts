"use server";

/* Действия реестра ошибок.

   Адрес действия выбирается из закрытого списка: серверное действие вызывается и в обход
   отрисованной страницы, и подставить в адрес API пришедшую строку значило бы дать снаружи
   выбирать, куда пойдёт запрос. Какие действия допустимы сейчас, решает API: здесь только
   передача. */

import { revalidatePath } from "next/cache";

import { ApiError, apiFetch } from "../../lib/api";
import { accessToken, organizationId } from "../../lib/session";
import type { IssueCategory, IssueSeverity } from "../../lib/work";

export type IssueResult = { error?: string; id?: string; done?: boolean };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const DAMAGED = "Запрос повреждён — обновите страницу";

// Действие и его адрес. `fix`, смена разряда и назначение — отдельными функциями: у них свои поля.
const DECISIONS = {
  confirm: "confirm",
  reject: "reject",
  request_clarification: "clarification",
  answer_clarification: "clarification/answer",
  verify: "verification",
  close: "close",
  reopen: "reopen",
  comment: "comments",
  archive: "archive",
} as const;

export type IssueDecision = keyof typeof DECISIONS;

function failure(error: unknown): IssueResult {
  if (error instanceof ApiError) {
    return { error: error.message };
  }

  return { error: "Сервис недоступен. Попробуйте ещё раз." };
}

async function send<T>(path: string, body: unknown): Promise<T> {
  const token = await accessToken();

  if (token === undefined) {
    throw new ApiError(401, "Сеанс закончился — войдите заново");
  }

  return apiFetch<T>(path, {
    method: "POST",
    token,
    organizationId: await organizationId(),
    body,
  });
}

function refresh(issueId: string): void {
  revalidatePath(`/app/issues/${issueId}`);
  revalidatePath("/app/issues");
  revalidatePath("/app");
}

export type IssueDraft = {
  block_id: string | null;
  object_id: string | null;
  category: IssueCategory;
  severity: IssueSeverity;
  description: string;
  proposed_fix: string | null;
};

/** Зарегистрировать ошибку. Код и снимки подставит сервер. */
export async function registerIssue(draft: IssueDraft): Promise<IssueResult> {
  const subjects = [draft.block_id, draft.object_id].filter((item) => item !== null);

  if (subjects.length === 0 || subjects.some((item) => !UUID.test(item))) {
    return { error: DAMAGED };
  }

  try {
    const created = await send<{ id: string }>("/issues", {
      block_id: draft.block_id,
      object_id: draft.object_id,
      category: draft.category,
      severity: draft.severity,
      description: draft.description,
      proposed_fix: draft.proposed_fix,
    });

    revalidatePath("/app/issues");
    revalidatePath("/app");

    return { id: created.id };
  } catch (error) {
    return failure(error);
  }
}

/** Решение по замечанию: подтвердить, отклонить, закрыть и так далее. */
export async function decideIssue(
  issueId: string,
  decision: IssueDecision,
  note: string,
): Promise<IssueResult> {
  if (!UUID.test(issueId) || !Object.hasOwn(DECISIONS, decision)) {
    return { error: DAMAGED };
  }

  try {
    const text = note.trim();

    await send(`/issues/${issueId}/${DECISIONS[decision]}`, { note: text === "" ? null : text });
    refresh(issueId);

    return { done: true };
  } catch (error) {
    return failure(error);
  }
}

/** Связать подтверждённое замечание с исправляющей редакцией. */
export async function fixIssue(
  issueId: string,
  revisionId: string,
  note: string,
): Promise<IssueResult> {
  if (!UUID.test(issueId) || !UUID.test(revisionId)) {
    return { error: DAMAGED };
  }

  try {
    const text = note.trim();

    await send(`/issues/${issueId}/fix`, {
      revision_id: revisionId,
      note: text === "" ? null : text,
    });
    refresh(issueId);

    return { done: true };
  } catch (error) {
    return failure(error);
  }
}

/** Исправить текст: новая редакция. Другая текущая редакция вернётся конфликтом. */
export async function editIssue(
  issueId: string,
  blockId: string,
  baseRevisionId: string,
  text: string,
  note: string,
): Promise<IssueResult> {
  if (!UUID.test(issueId) || !UUID.test(blockId) || !UUID.test(baseRevisionId)) {
    return { error: DAMAGED };
  }

  try {
    const clean = note.trim();

    await send(`/issues/${issueId}/revision`, {
      block_id: blockId,
      base_revision_id: baseRevisionId,
      text,
      note: clean === "" ? null : clean,
    });
    refresh(issueId);

    return { done: true };
  } catch (error) {
    return failure(error);
  }
}

/** Применить исправление к выбранным повторам. */
export async function applyRegression(
  runId: string,
  issueId: string,
  itemIds: string[],
  overwriteFinal: boolean,
  note: string,
): Promise<IssueResult> {
  if (!UUID.test(runId) || !UUID.test(issueId) || itemIds.some((id) => !UUID.test(id))) {
    return { error: DAMAGED };
  }

  try {
    const clean = note.trim();

    await send(`/regression-runs/${runId}/apply`, {
      item_ids: itemIds,
      overwrite_final: overwriteFinal === true,
      note: clean === "" ? null : clean,
    });
    refresh(issueId);

    return { done: true };
  } catch (error) {
    return failure(error);
  }
}

/** Решение по одному затронутому месту. */
export async function decideRegression(
  itemId: string,
  issueId: string,
  payload: {
    affected: boolean;
    note: string | null;
    category: IssueCategory | null;
    severity: IssueSeverity | null;
  },
): Promise<IssueResult> {
  if (!UUID.test(itemId) || !UUID.test(issueId)) {
    return { error: DAMAGED };
  }

  try {
    await send(`/regression-items/${itemId}/decision`, {
      affected: payload.affected === true,
      note: payload.note,
      category: payload.category,
      severity: payload.severity,
    });
    refresh(issueId);

    return { done: true };
  } catch (error) {
    return failure(error);
  }
}

export async function restoreIssue(issueId: string): Promise<IssueResult> {
  if (!UUID.test(issueId)) {
    return { error: DAMAGED };
  }

  try {
    await send(`/issues/${issueId}/restore`, undefined);
    refresh(issueId);

    return { done: true };
  } catch (error) {
    return failure(error);
  }
}

export async function reclassifyIssue(
  issueId: string,
  change: { reason: string; category: IssueCategory; severity: IssueSeverity },
): Promise<IssueResult> {
  if (!UUID.test(issueId)) {
    return { error: DAMAGED };
  }

  try {
    await send(`/issues/${issueId}/classification`, {
      reason: change.reason.trim(),
      category: change.category,
      severity: change.severity,
    });
    refresh(issueId);

    return { done: true };
  } catch (error) {
    return failure(error);
  }
}

export async function assignIssue(issueId: string, assigneeId: string | null): Promise<IssueResult> {
  if (!UUID.test(issueId) || (assigneeId !== null && !UUID.test(assigneeId))) {
    return { error: DAMAGED };
  }

  try {
    await send(`/issues/${issueId}/assignee`, { assignee_id: assigneeId });
    refresh(issueId);

    return { done: true };
  } catch (error) {
    return failure(error);
  }
}
