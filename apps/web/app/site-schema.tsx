/* Микроразметка главной — schema.org в JSON-LD.
 *
 * Один граф вместо пяти отдельных блоков: сущности ссылаются друг на
 * друга по `@id`, и поисковик видит, что сайт, организация и приложение —
 * про одно и то же. Цены и оценок здесь нет намеренно: публичного
 * прейскуранта у продукта нет, а выдуманный рейтинг — обман, за который
 * поисковики наказывают.
 *
 * Вопросы и ответы берутся те же, что показаны на странице: разметка
 * обязана описывать видимое, а не то, что хотелось бы показать роботу.
 *
 * 🔥 У страниц на разных языках разные `@id`. Один и тот же
 * идентификатор на двух документах означает для поисковика, что это один
 * документ, — и один из двух он выкинет. Общими остаются организация и
 * сайт: они и правда одни.
 */

import { CONTACT_EMAIL, SITE_NAME, SITE_URL } from "./contacts";
import { dictionary } from "./i18n";
import { localePath, type Locale } from "./i18n/config";

export type Faq = { q: string; a: string };

const ORGANIZATION = `${SITE_URL}/#organization`;
const WEBSITE = `${SITE_URL}/#website`;

export function SiteSchema({
  lang,
  faq,
  features,
}: {
  lang: Locale;
  faq: Faq[];
  features: string[];
}) {
  const t = dictionary(lang);
  const home = `${SITE_URL}${localePath(lang, "/")}`;
  // У русской главной адрес кончается косой чертой, у английской — нет:
  // `/en/` и `/en` для поисковика два разных адреса, и канонический из них
  // тот, что стоит в ссылках и в карте сайта.
  const page = lang === "ru" ? `${SITE_URL}/` : home;

  const graph = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "Organization",
        "@id": ORGANIZATION,
        name: SITE_NAME,
        url: `${SITE_URL}/`,
        logo: `${SITE_URL}/icons/icon-512.png`,
        email: CONTACT_EMAIL,
      },
      {
        "@type": "WebSite",
        "@id": WEBSITE,
        url: `${SITE_URL}/`,
        name: SITE_NAME,
        description: t.meta.description,
        inLanguage: t.htmlLang,
        publisher: { "@id": ORGANIZATION },
      },
      {
        "@type": "WebPage",
        "@id": `${page}#webpage`,
        url: page,
        name: t.meta.pageName,
        description: t.meta.description,
        inLanguage: t.htmlLang,
        isPartOf: { "@id": WEBSITE },
        about: { "@id": ORGANIZATION },
      },
      {
        "@type": "SoftwareApplication",
        "@id": `${SITE_URL}/#application`,
        name: SITE_NAME,
        url: `${SITE_URL}/`,
        description: t.meta.description,
        applicationCategory: "BusinessApplication",
        operatingSystem: "Web",
        inLanguage: t.htmlLang,
        featureList: features,
        publisher: { "@id": ORGANIZATION },
      },
      {
        "@type": "FAQPage",
        "@id": `${page}#faq`,
        inLanguage: t.htmlLang,
        mainEntity: faq.map((item) => ({
          "@type": "Question",
          name: item.q,
          acceptedAnswer: { "@type": "Answer", text: item.a },
        })),
      },
    ],
  };

  return (
    <script
      type="application/ld+json"
      // `<` заменяется на юникод-последовательность: JSON внутри <script>
      // не экранируется разметкой, и строка `</script>` в тексте ответа
      // закрыла бы блок и открыла посторонний сценарий.
      dangerouslySetInnerHTML={{ __html: JSON.stringify(graph).replace(/</g, "\\u003c") }}
    />
  );
}
