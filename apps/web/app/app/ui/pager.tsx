/* Переход по страницам списка.

   Ссылками, а не кнопками: страница — это адрес, и «назад» в браузере
   обязан возвращать на предыдущую страницу списка, а не мимо неё.

   Номер страницы считается из смещения, а смещение остаётся в адресе:
   номер пришлось бы умножать на размер страницы в двух местах — здесь и
   в запросе к API, — и эти два места однажды разойдутся на единицу.

   Счёт — числами, без слова: слово с числом уже стоит в заголовке
   списка, а здесь после «из» ему понадобился бы родительный падеж, и
   «из 2 книги» читалось бы как ошибка перевода. */

import Link from "next/link";

import { thousands } from "../labels";
import { linkTo } from "./query";

export function Pager({
  total,
  limit,
  offset,
  path,
  params,
}: {
  total: number;
  limit: number;
  offset: number;
  path: string;
  params: URLSearchParams;
}) {
  // Одна страница — ни счёта, ни кнопок: список и так виден целиком.
  if (total <= limit && offset === 0) {
    return null;
  }

  // Смещение за концом списка: номер подобран в адресе или список
  // сократился, пока страница была открыта. Шаг «назад» здесь привёл бы
  // на такую же пустую страницу — ведём сразу на последнюю настоящую.
  if (offset >= total) {
    const lastPage = total === 0 ? 0 : Math.floor((total - 1) / limit) * limit;

    return (
      <nav className="ui-pager" aria-label="Страницы списка">
        <p className="tile__note">Такой страницы в списке нет.</p>

        <span className="ui-pager__go">
          <Link
            className="btn btn--ghost btn--small"
            href={linkTo(path, params, { offset: lastPage === 0 ? null : lastPage })}
          >
            {lastPage === 0 ? "К началу списка" : "К последней странице"}
          </Link>
        </span>
      </nav>
    );
  }

  const page = Math.floor(offset / limit) + 1;
  const pages = Math.ceil(total / limit);
  const last = Math.min(offset + limit, total);
  const previous = Math.max(0, offset - limit);

  return (
    <nav className="ui-pager" aria-label="Страницы списка">
      <p className="tile__note">
        {thousands(offset + 1)}–{thousands(last)} из {thousands(total)} · страница {page} из{" "}
        {pages}
      </p>

      <span className="ui-pager__go">
        {/* Отсутствующая страница — текст, а не выключенная ссылка:
            выключенную ссылку браузер всё равно откроет по Enter. */}
        {offset > 0 ? (
          <Link
            className="btn btn--ghost btn--small"
            // Первая страница — без параметра: у неё один адрес, а не два.
            href={linkTo(path, params, { offset: previous === 0 ? null : previous })}
            rel="prev"
          >
            Назад
          </Link>
        ) : (
          <span className="btn btn--ghost btn--small is-off" aria-hidden="true">
            Назад
          </span>
        )}

        {last < total ? (
          <Link
            className="btn btn--ghost btn--small"
            href={linkTo(path, params, { offset: offset + limit })}
            rel="next"
          >
            Дальше
          </Link>
        ) : (
          <span className="btn btn--ghost btn--small is-off" aria-hidden="true">
            Дальше
          </span>
        )}
      </span>
    </nav>
  );
}
