"use server";

/* Действия редактора: поправить, принять, вернуть в работу.

   По одному сегменту, а не пачкой — в отличие от терминов. Причина не в
   удобстве: правка расходится по повторам и вытесняет машинный вариант из
   памяти переводов, и число подтянувшихся повторов редактор должен увидеть
   сразу после своего действия. Пачка из сорока правок ответила бы одним
   числом на все, и понять, какая именно строка изменила сорок мест в книге,
   было бы уже нельзя.

   🔥 Здесь намеренно нет `revalidatePath`. Очередь — живой список, который
   человек разбирает сверху вниз; перерисовка страницы после каждого
   действия убирала бы строки из-под курсора. Список обновляется по явному
   нажатию, и тогда же `router.refresh()` сбрасывает клиентский кеш целиком.
   Данные при этом не устаревают: `apiFetch` ходит с `cache: "no-store"`. */

import { ApiError, apiFetch } from "../../lib/api";
import { accessToken, organizationId } from "../../lib/session";
import type { Segment } from "../../lib/work";

export type Saved = {
  segment: Segment;
  // Сколько повторов того же исходника подтянулось за правкой. Редактор
  // поправил одну строку, а изменилось сорок — знать об этом он должен до
  // того, как увидит это в готовой книге.
  propagated: number;
};

export type EditResult = { error?: string; saved?: Saved };
export type SegmentResult = { error?: string; segment?: Segment };
export type CleanResult = { error?: string; approved?: number };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Потолок правки — тот же, что у API: длиннее он всё равно не примет, и
// сказать об этом до запроса честнее, чем показать отказ схемы.
const MAX_LENGTH = 20000;

function failure(error: unknown): { error: string } {
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

/** Записать правку редактора.
 *
 * Пустой текст не отправляется вовсе: «стереть перевод» — это не правка, а
 * возврат к непереведённому состоянию, и делается он повторным переводом.
 */
export async function editSegment(segmentId: string, targetText: string): Promise<EditResult> {
  if (!UUID.test(segmentId)) {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  const text = targetText.trim();

  if (text === "") {
    return { error: "Перевод не может быть пустым" };
  }

  if (text.length > MAX_LENGTH) {
    return { error: `Перевод длиннее ${MAX_LENGTH} знаков — столько API не примет` };
  }

  try {
    const { token, organizationId: organization } = await credentials();

    const saved = await apiFetch<Saved>(`/segments/${segmentId}`, {
      method: "PATCH",
      token,
      organizationId: organization,
      body: { target_text: text },
    });

    return { saved };
  } catch (error) {
    return failure(error);
  }
}

/** Принять сегмент.
 *
 * Отдельным действием от правки намеренно: «я это поправил» и «я за это
 * отвечаю» — разные утверждения. Принять сегмент с находками можно:
 * проверка машинная и ошибается, а отвечает за текст человек.
 */
export async function approveSegment(segmentId: string): Promise<SegmentResult> {
  if (!UUID.test(segmentId)) {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  try {
    const { token, organizationId: organization } = await credentials();

    const segment = await apiFetch<Segment>(`/segments/${segmentId}/approve`, {
      method: "POST",
      token,
      organizationId: organization,
    });

    return { segment };
  } catch (error) {
    return failure(error);
  }
}

/** Вернуть принятый сегмент в работу — на случай промаха по кнопке. */
export async function reopenSegment(segmentId: string): Promise<SegmentResult> {
  if (!UUID.test(segmentId)) {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  try {
    const { token, organizationId: organization } = await credentials();

    const segment = await apiFetch<Segment>(`/segments/${segmentId}/reopen`, {
      method: "POST",
      token,
      organizationId: organization,
    });

    return { segment };
  } catch (error) {
    return failure(error);
  }
}

/** Принять всё, к чему у проверок нет претензий.
 *
 * Без этого приёмка книги — три тысячи нажатий, и делать её никто не
 * станет. Помеченное остаётся редактору: смысл разделения в том, чтобы его
 * внимание доставалось спорному, а не всему подряд.
 */
export async function approveClean(documentId: string): Promise<CleanResult> {
  if (!UUID.test(documentId)) {
    return { error: "Запрос повреждён — обновите страницу" };
  }

  try {
    const { token, organizationId: organization } = await credentials();

    const answer = await apiFetch<{ approved: number }>(
      `/documents/${documentId}/segments/approve-clean`,
      { method: "POST", token, organizationId: organization },
    );

    return { approved: answer.approved };
  } catch (error) {
    return failure(error);
  }
}
