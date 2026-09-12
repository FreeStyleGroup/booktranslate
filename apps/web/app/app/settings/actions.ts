"use server";

/* Настройки рабочего пространства.

   Ключа бота здесь нет: бот один на всю площадку и живёт в её настройках.
   Заказчик указывает только ник — и тем самым не доверяет нам ничего, чем
   можно было бы воспользоваться. */

import { revalidatePath } from "next/cache";

import { ApiError, apiFetch } from "../../lib/api";
import { accessToken, organizationId } from "../../lib/session";

export type NotificationSettings = {
  email_enabled: boolean;
  // Не «кому», а «кому ещё»: письмо и так уходит тому, кто поставил книгу
  // в очередь, — на почту его учётной записи.
  email_extra: string | null;
  telegram_enabled: boolean;
  // Ник без «собачки»: она часть записи, а не имени.
  telegram_username: string | null;
  // Написал ли человек боту. Пока нет — отправить ему нельзя: Телеграм не
  // даёт писать по нику, нужен номер разговора.
  telegram_linked: boolean;
  // Умеет ли канал отправлять на самом деле. Пока нет — и интерфейс обязан
  // об этом сказать, а не делать вид, что уведомления пойдут.
  email_ready: boolean;
  telegram_ready: boolean;
};

export type Result = {
  error?: string;
  saved?: NotificationSettings;
  // Когда записали. Не для показа: по нему форма пересобирается после
  // каждой записи — см. 🔥 в notifications.tsx.
  savedAt?: number;
};

export async function saveNotifications(
  _previous: Result,
  formData: FormData,
): Promise<Result> {
  try {
    const token = await accessToken();

    if (token === undefined) {
      return { error: "Сеанс закончился — войдите заново" };
    }

    const saved = await apiFetch<NotificationSettings>("/settings/notifications", {
      method: "PUT",
      token,
      organizationId: await organizationId(),
      body: {
        email_enabled: formData.get("email_enabled") === "yes",
        email_extra: String(formData.get("email_extra") ?? "").trim(),
        telegram_enabled: formData.get("telegram_enabled") === "yes",
        telegram_username: String(formData.get("telegram_username") ?? "").trim(),
      },
    });

    revalidatePath("/app/settings");

    return { saved, savedAt: Date.now() };
  } catch (error) {
    if (error instanceof ApiError) {
      return { error: error.message };
    }

    return { error: "Сервис недоступен. Попробуйте ещё раз." };
  }
}
