/* Диаграммы расхода.

   Без библиотеки. Здесь три простые картинки — столбцы по месяцам и две
   ленты долей, — а библиотека графиков это сотни килобайт в браузере
   человека и зависимость на годы. Столбцы собраны сеткой, ленты —
   полосами: и то и другое читает тёмную тему само, потому что цвета
   берутся из переменных оформления.

   Серверные компоненты: ничего интерактивного здесь нет, и уезжать в
   браузер незачем. Подсказку по наведению рисует сам браузер из `title`. */

import { thousands } from "../labels";

/** Цвета моделей. Порядок постоянный, поэтому одна и та же модель красится
 *  одинаково и в столбцах месяца, и в ленте долей — иначе сравнивать их
 *  между собой пришлось бы по подписям. */
const COLORS = ["#2f6bff", "#12b981", "#8b5cf6", "#f0a63a", "#0ea5a5", "#ef4444"];

export function colorFor(models: string[], model: string): string {
  const index = models.indexOf(model);

  return COLORS[(index < 0 ? models.length : index) % COLORS.length];
}

export type Part = { key: string; value: number; color: string; label: string };

/** Столбцы по месяцам, каждый разложен по моделям.
 *
 * Высота столбца — доля от самого дорогого месяца. Числа подписаны не у
 * каждого столбца, а у самого высокого и в подсказке: двенадцать чисел
 * подряд читаются хуже, чем одна картинка.
 */
export function Months({
  months,
}: {
  months: { month: string; total: number; parts: Part[] }[];
}) {
  const peak = Math.max(1, ...months.map((month) => month.total));

  return (
    <div className="us-months" role="img" aria-label="Расход по месяцам">
      {months.map((month) => (
        <div className="us-month" key={month.month}>
          <div
            className="us-month__bar"
            style={{ height: `${Math.max(2, (month.total * 100) / peak)}%` }}
            title={`${title(month.month)}: ${thousands(month.total)} токенов`}
          >
            {month.parts.map((part) => (
              <i
                key={part.key}
                style={{
                  height: `${(part.value * 100) / Math.max(1, month.total)}%`,
                  background: part.color,
                }}
                title={`${part.label}: ${thousands(part.value)}`}
              />
            ))}
          </div>
          <span className="us-month__name">{short(month.month)}</span>
        </div>
      ))}
    </div>
  );
}

/** Лента долей: одна строка, в ней куски по моделям.
 *
 * Кольцевая диаграмма на её месте выглядела бы наряднее и читалась бы
 * хуже: доли в ленте сравниваются глазом по длине, а в кольце — по углу.
 */
export function Share({ parts }: { parts: Part[] }) {
  const total = Math.max(
    1,
    parts.reduce((sum, part) => sum + part.value, 0),
  );

  return (
    <div className="us-share" role="img" aria-label="Доли моделей в расходе">
      {parts.map((part) => (
        <i
          key={part.key}
          style={{ width: `${(part.value * 100) / total}%`, background: part.color }}
          title={`${part.label}: ${thousands(part.value)} токенов`}
        />
      ))}
    </div>
  );
}

/** Подписи к цветам. Без них лента — просто полоска. */
export function Legend({ parts }: { parts: Part[] }) {
  return (
    <ul className="us-legend">
      {parts.map((part) => (
        <li key={part.key}>
          <i style={{ background: part.color }} aria-hidden="true" />
          <span>{part.label}</span>
          <b>{thousands(part.value)}</b>
        </li>
      ))}
    </ul>
  );
}

const MONTHS = [
  "январь",
  "февраль",
  "март",
  "апрель",
  "май",
  "июнь",
  "июль",
  "август",
  "сентябрь",
  "октябрь",
  "ноябрь",
  "декабрь",
];

/** «2026-09» → «сентябрь 2026». */
function title(month: string): string {
  const [year, number] = month.split("-");

  return `${MONTHS[Number(number) - 1] ?? month} ${year}`;
}

/** «2026-09» → «сен». Под столбцом места на полное название нет. */
function short(month: string): string {
  const [, number] = month.split("-");

  return (MONTHS[Number(number) - 1] ?? month).slice(0, 3);
}
