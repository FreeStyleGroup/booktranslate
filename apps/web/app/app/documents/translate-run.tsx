"use client";

/* Перевод книги.

   Идёт порциями, а цикл крутит витрина. Причина не в удобстве: книга на
   четыреста страниц переводится часами, а обратный прокси режет соединение
   через четверть часа — один запрос на всю книгу до ответа не доживёт. API
   отвечает после каждой порции, сколько осталось, и мы зовём его, пока
   остаток не станет нулём.

   Отсюда же и честность: сделанное фиксируется в базе после каждой пачки.
   Закрытая вкладка, нажатая остановка, оборванная связь — всё это теряет
   не перевод, а только цикл. Следующий запуск продолжит с того же места и
   не заплатит второй раз за уже переведённое.

   🔥 Чего здесь нет и не должно быть: автоматического повтора после
   отказа. Каждое обращение к модели стоит денег, и цикл, который сам
   ломится в стену, потратит их быстрее, чем человек успеет прочитать
   сообщение об ошибке. */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { plural, thousands } from "../labels";
import { translateChunk, type Chunk } from "../actions";

/** Книга без терминологического прохода: что делать дальше.
 *
 * Два выхода, а не один. Проход — правильный путь, и он первый. Но
 * запретить перевод без него нельзя: у короткой книги на три страницы
 * терминология не окупается, и человек, которому надо просто посмотреть,
 * как оно работает, не должен упираться в стену. Цена решения написана
 * рядом, а не спрятана.
 */
export function BeforeTranslate({
  documentId,
  untranslated,
}: {
  documentId: string;
  untranslated: number;
}) {
  const [skip, setSkip] = useState(false);

  if (skip) {
    return <TranslateRun documentId={documentId} untranslated={untranslated} />;
  }

  return (
    <section className="tile wk-call">
      <h3>Следующий шаг — термины</h3>
      <p>
        Программа пройдёт по тексту и соберёт то, что в нём повторяется:
        термины, аббревиатуры, обозначения. Решается это один раз и до
        перевода, а дальше держит всю книгу и все следующие книги проекта.
      </p>
      <div className="tile__foot">
        <Link className="btn btn--primary btn--small" href={`/app/terms?document=${documentId}`}>
          Термины книги
        </Link>
        <button
          className="btn btn--ghost btn--small"
          type="button"
          onClick={() => setSkip(true)}
        >
          Перевести без словаря
        </button>
      </div>
      <p className="tile__note wk-seg__foot">
        Без словаря перевод тоже пойдёт, но каждое незнакомое слово модель
        решит сама и в разных местах по-разному. На короткой книге это
        терпимо, на руководстве в четыреста страниц — нет.
      </p>
    </section>
  );
}

type Tally = {
  done: number;
  fromMemory: number;
  fromProvider: number;
  flagged: number;
  savedCalls: number;
  inputTokens: number;
  outputTokens: number;
  usd: number | null;
};

const EMPTY: Tally = {
  done: 0,
  fromMemory: 0,
  fromProvider: 0,
  flagged: 0,
  savedCalls: 0,
  inputTokens: 0,
  outputTokens: 0,
  usd: null,
};

function add(tally: Tally, chunk: Chunk): Tally {
  return {
    done: tally.done + chunk.total,
    fromMemory: tally.fromMemory + chunk.from_memory,
    fromProvider: tally.fromProvider + chunk.from_provider,
    flagged: tally.flagged + chunk.flagged,
    savedCalls: tally.savedCalls + chunk.saved_calls,
    inputTokens: tally.inputTokens + chunk.input_tokens,
    outputTokens: tally.outputTokens + chunk.output_tokens,
    // Стоимость складывается только из того, что посчиталось: у заглушки и
    // у модели вне прейскуранта её нет вовсе, и подставлять ноль нельзя.
    usd:
      chunk.estimated_usd === null
        ? tally.usd
        : (tally.usd ?? 0) + chunk.estimated_usd,
  };
}

export function TranslateRun({
  documentId,
  untranslated,
}: {
  documentId: string;
  untranslated: number;
}) {
  const router = useRouter();

  const [running, setRunning] = useState(false);
  const [left, setLeft] = useState(untranslated);
  const [tally, setTally] = useState<Tally>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [finished, setFinished] = useState(false);

  // Остановка читается внутри цикла, поэтому ссылкой, а не состоянием:
  // состояние, прочитанное из замыкания цикла, навсегда осталось бы тем,
  // каким было при запуске.
  const stop = useRef(false);

  async function run(): Promise<void> {
    stop.current = false;
    setRunning(true);
    setError(null);
    setFinished(false);
    setTally(EMPTY);

    let more = true;

    while (more && !stop.current) {
      const answer = await translateChunk(documentId);

      if (answer.error !== undefined || answer.chunk === undefined) {
        setError(answer.error ?? "Перевод не удался");
        break;
      }

      const chunk = answer.chunk;

      setTally((was) => add(was, chunk));
      setLeft(chunk.remaining);

      // Ноль в остатке — книга переведена. Ноль во взятых сегментах при
      // ненулевом остатке означал бы, что цикл крутится впустую: такого
      // быть не должно, но останавливаемся и здесь, чтобы не молотить.
      more = chunk.remaining > 0 && chunk.total > 0;

      if (chunk.remaining === 0) {
        setFinished(true);
      }
    }

    setRunning(false);
    router.refresh();
  }

  const done = untranslated - left;
  const percent = untranslated === 0 ? 100 : Math.round((done * 100) / untranslated);

  return (
    <section className="tile wk-call">
      <h3>{finished ? "Книга переведена" : "Перевод"}</h3>

      {!running && !finished && (
        <p>
          Модель получит сегменты вместе с решёнными терминами и соседними
          абзацами — без них «он», «указанный выше» и опущенное подлежащее
          переводятся наугад. Повторы внутри книги и то, что уже есть в памяти
          переводов, в модель не уйдут вовсе.
        </p>
      )}

      {(running || tally.done > 0) && (
        <>
          <div className="tr-bar">
            <div className="bar">
              <i style={{ width: `${percent}%` }} />
            </div>
            <b>{percent}%</b>
          </div>

          <p className="tile__note">
            Переведено {thousands(done)} из {thousands(untranslated)}{" "}
            {plural(untranslated, "сегмента", "сегментов", "сегментов")}
            {tally.fromMemory > 0 && `, из них ${thousands(tally.fromMemory)} закрыла память`}
            {tally.flagged > 0 &&
              ` · с замечаниями ${thousands(tally.flagged)}`}
            {tally.usd !== null && ` · ≈ $${tally.usd.toFixed(2)}`}
          </p>
        </>
      )}

      {error !== null && (
        <p className="form__error" role="alert">
          {error}
        </p>
      )}

      {finished && (
        <p>
          Перевод готов и ждёт человека. Сегменты с замечаниями собраны в
          очередь: проверки нашли расхождение чисел, нарушение термина или
          потерянную подстановку — это не приговор переводу, а список мест,
          на которые стоит посмотреть.
        </p>
      )}

      <div className="tile__foot">
        {running ? (
          <button
            className="btn btn--ghost btn--small"
            type="button"
            onClick={() => {
              stop.current = true;
            }}
          >
            Остановить
          </button>
        ) : (
          <button
            className="btn btn--primary btn--small"
            type="button"
            onClick={() => void run()}
            disabled={left === 0}
          >
            {tally.done > 0 && left > 0 ? "Продолжить" : "Перевести книгу"}
          </button>
        )}
      </div>

      {running && (
        <p className="tile__note wk-seg__foot">
          Идёт перевод. Страницу можно закрыть — сделанное уже записано, и
          следующий запуск продолжит с того же места, не заплатив второй раз
          за переведённое. Но сам перевод при закрытой вкладке остановится:
          цикл крутит эта страница.
        </p>
      )}
    </section>
  );
}
