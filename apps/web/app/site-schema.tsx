/* Микроразметка главной — schema.org в JSON-LD.
 *
 * Один граф вместо пяти отдельных блоков: сущности ссылаются друг на
 * друга по `@id`, и поисковик видит, что сайт, организация и приложение —
 * про одно и то же. Цены и оценок здесь нет намеренно: публичного
 * прейскуранта у продукта нет, а выдуманный рейтинг — обман, за который
 * поисковики наказывают.
 *
 * Вопросы и ответы берутся те же, что показаны на странице: разметка
 * обязана описывать видимое, а не то, что хотелось бы показать роботу. */

import { CONTACT_EMAIL, SITE_DESCRIPTION, SITE_NAME, SITE_URL } from "./contacts";

export type Faq = { q: string; a: string };

const ORGANIZATION = `${SITE_URL}/#organization`;
const WEBSITE = `${SITE_URL}/#website`;

export function SiteSchema({ faq, features }: { faq: Faq[]; features: string[] }) {
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
        description: SITE_DESCRIPTION,
        inLanguage: "ru",
        publisher: { "@id": ORGANIZATION },
      },
      {
        "@type": "WebPage",
        "@id": `${SITE_URL}/#webpage`,
        url: `${SITE_URL}/`,
        name: `${SITE_NAME} — профессиональный перевод технических книг`,
        description: SITE_DESCRIPTION,
        inLanguage: "ru",
        isPartOf: { "@id": WEBSITE },
        about: { "@id": ORGANIZATION },
      },
      {
        "@type": "SoftwareApplication",
        "@id": `${SITE_URL}/#application`,
        name: SITE_NAME,
        url: `${SITE_URL}/`,
        description: SITE_DESCRIPTION,
        applicationCategory: "BusinessApplication",
        operatingSystem: "Web",
        inLanguage: "ru",
        featureList: features,
        publisher: { "@id": ORGANIZATION },
      },
      {
        "@type": "FAQPage",
        "@id": `${SITE_URL}/#faq`,
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
