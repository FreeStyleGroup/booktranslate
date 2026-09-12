"use server";

/* Команда: пригласить, сменить роль, убрать, отозвать приглашение.

   Серверные действия, а не запросы из браузера: токен живёт в
   httpOnly-печенье и в браузер не попадает. Отказ API уходит на страницу
   словами — «свою роль не меняют», «назначить владельца может только
   владелец» — а не кодом ответа. */

import { revalidatePath } from "next/cache";

import { ApiError, apiFetch } from "../../lib/api";
import { accessToken, organizationId } from "../../lib/session";
import type { Invitation, Role } from "../../lib/work";

export type Result = { error?: string };

export type Invited = {
  invitation: Invitation;
  // Показывается один раз: если письмо не ушло, ссылку передают сами.
  link: string;
  email_sent: boolean;
  email_detail: string;
};

export type InviteResult = Result & {
  invited?: Invited;
  // Когда выписали. По нему форма пересобирается после каждой выписки —
  // тот же приём, что в настройках уведомлений.
  at?: number;
};

/** Запрос от имени вошедшего в текущем пространстве. */
async function call<T>(path: string, method: string, body?: unknown): Promise<T> {
  const token = await accessToken();

  if (token === undefined) {
    throw new ApiError(401, "Сеанс закончился — войдите заново");
  }

  return apiFetch<T>(path, { method, token, organizationId: await organizationId(), body });
}

function failure(error: unknown): Result {
  if (error instanceof ApiError) {
    return { error: error.message };
  }

  return { error: "Сервис недоступен. Попробуйте ещё раз." };
}

export async function inviteMember(_previous: InviteResult, formData: FormData): Promise<InviteResult> {
  try {
    const invited = await call<Invited>("/team/invitations", "POST", {
      email: String(formData.get("email") ?? "").trim(),
      role: String(formData.get("role") ?? "translator"),
    });

    revalidatePath("/app/team");

    return { invited, at: Date.now() };
  } catch (error) {
    return failure(error);
  }
}

export async function changeRole(userId: string, role: Role): Promise<Result> {
  try {
    await call(`/team/members/${userId}`, "PATCH", { role });
    revalidatePath("/app/team");

    return {};
  } catch (error) {
    return failure(error);
  }
}

export async function removeMember(userId: string): Promise<Result> {
  try {
    await call(`/team/members/${userId}`, "DELETE");
    revalidatePath("/app/team");

    return {};
  } catch (error) {
    return failure(error);
  }
}

export async function revokeInvitation(invitationId: string): Promise<Result> {
  try {
    await call(`/team/invitations/${invitationId}`, "DELETE");
    revalidatePath("/app/team");

    return {};
  } catch (error) {
    return failure(error);
  }
}
