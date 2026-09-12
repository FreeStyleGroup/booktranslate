import { notFound } from "next/navigation";

/* Разделы кабинета, которые ещё делаются.

   Одна страница на все, а не десять одинаковых заглушек: пока раздел не
   написан, честнее показать, что в нём будет, чем вести человека в пустоту
   или в ошибку 404. Неизвестный адрес по-прежнему даёт 404 — иначе кабинет
   отвечал бы «скоро» на любую опечатку. */

const SECTIONS: Record<string, { icon: string; title: string; lead: string; items: string[] }> = {
  catalog: {
    icon: "🔍",
    title: "Каталог справок",
    lead: "Что бюро уже выяснило про незнакомые слова — с источниками.",
    items: [
      "Поиск по термину, переводу и определению",
      "Запрос справки во внешнем источнике",
      "Видно, сколько справок досталось из каталога бесплатно",
    ],
  },
  glossary: {
    icon: "📑",
    title: "Словарь",
    lead: "Решения: как это называется у заказчика.",
    items: [
      "Разряд записи и состояние решения",
      "Загрузка CSV, TBX и рабочих реестров в DOCX",
      "Заведённое человеком не перезаписывается загрузкой",
    ],
  },
  memory: {
    icon: "🧠",
    title: "Память переводов",
    lead: "Пары «исходник — перевод», накопленные по всем книгам.",
    items: [
      "Сколько раз пара пригодилась",
      "Правка человека вытесняет машинный вариант",
      "Экономия на повторном заказе — в цифрах",
    ],
  },
  team: {
    icon: "👥",
    title: "Команда",
    lead: "Кто работает в рабочем пространстве и что кому доступно.",
    items: ["Приглашения по почте", "Роли: менеджер, переводчик, редактор, наблюдатель"],
  },
};

export default async function SectionPage({ params }: { params: Promise<{ section: string }> }) {
  const { section } = await params;
  const page = SECTIONS[section];

  if (page === undefined) {
    notFound();
  }

  return (
    <section className="tile soon">
      <span className="soon__mark" aria-hidden="true">
        {page.icon}
      </span>
      <h2>{page.title}</h2>
      <p className="lead">{page.lead}</p>
      <ul className="points">
        {page.items.map((item) => (
          <li key={item}>
            <i aria-hidden="true">·</i>
            <span>{item}</span>
          </li>
        ))}
      </ul>
      <p className="demo-badge">
        <span aria-hidden="true">🔨</span> Раздел делается — конвейер под ним
        уже работает
      </p>
    </section>
  );
}
