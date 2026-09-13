/* English copy for the public site.
 *
 * Перевод, а не подстрочник: тон русского оригинала — прямой, конкретный,
 * без рекламных оборотов — сохранён, а обороты, которые по-английски
 * звучат калькой, переписаны. Форма словаря проверяется типом: ключ,
 * забытый здесь, роняет сборку, а не оставляет пустое место на странице.
 *
 * 🔥 Пример на главной здесь развёрнут: исходник русский, перевод
 * английский. Продукт работает в обе стороны, а читатель этой страницы
 * должен видеть результат на своём языке — колонку кириллицы он не
 * прочтёт и примет за непереведённый кусок сайта.
 */

import type { DemoCandidate, DemoSegment, Dictionary } from "./ru";

const SEGMENTS: DemoSegment[] = [
  {
    no: 214,
    src: "Отправьте запрос с заголовком Idempotency-Key, содержащим UUID.",
    dst: "Send the request with the Idempotency-Key header set to a UUID.",
    mark: "checked",
  },
  {
    no: 215,
    src: "Не превышайте предельный размер пула — 32 соединения.",
    dst: "Do not exceed the maximum pool size of 32 connections.",
    mark: "memory",
  },
  {
    no: 216,
    src: "Главный узел перезапускается вместе с набором реплик.",
    dst: "The primary node is restarted together with its replica set.",
    mark: "term",
  },
  {
    no: 217,
    src: "Полный список переменных окружения приведён в разделе 7.3.",
    dst: "The full list of environment variables is given in section 7.3.",
    mark: "checked",
  },
  {
    // Число в переводе не то, что в исходнике: ровно та ошибка, которую
    // ищет проверка чисел, и ровно та, которую человек не замечает.
    no: 218,
    src: "Токен доступа истекает через 3600 секунд.",
    dst: "The access token expires after 360 seconds.",
    mark: "numbers",
  },
];

const CANDIDATES: DemoCandidate[] = [
  { term: "набор реплик", freq: 34, verdict: "ok", note: "replica set" },
  { term: "ограничение частоты", freq: 21, verdict: "ok", note: "rate limit" },
  { term: "СУБД", freq: 18, verdict: "info", note: "expand on first use" },
  { term: "холодный старт", freq: 9, verdict: "warn", note: "awaiting a decision" },
  { term: "RFC 7519", freq: 4, verdict: "ok", note: "do not translate" },
];

export const en: Dictionary = {
  htmlLang: "en",
  ogLocale: "en_US",

  meta: {
    title: "BookTranslate — professional translation of technical books",
    description:
      "Professional translation of technical books and documentation: terminology is settled before translation, unfamiliar words get a sourced reference, every segment is checked, and the book is rebuilt into its original file. For students and for companies.",
    ogDescription:
      "Terms are settled before translation, numbers and notation do not drift, and the book is rebuilt into its own format with all of its formatting.",
    tagline: "professional translation of technical books and documentation",
    pageName: "BookTranslate — professional translation of technical books",
  },

  nav: {
    how: "How it works",
    terms: "Terminology",
    who: "Who it is for",
    formats: "Formats",
    price: "Cost",
    faq: "Questions",
    login: "Sign in",
    register: "Sign up",
    menuOpen: "Open menu",
    menuClose: "Close menu",
    language: "Interface language",
    theme: "Switch theme",
  },

  hero: {
    eyebrow: "Professional translation of technical books and documentation",
    titleBefore: "Translation you can",
    titleAccent: "check line by line",
    lead: "You cannot simply run an eight-hundred-page book through a translator. A mistake here is not a matter of style: it is a token lifetime, a rate limit, a field name in a request. So we parse the document and settle the terms first, translate second, check third — and put it all back into the same file, with every bit of its formatting.",
    flow: ["Book", "Terms", "Translation", "Checks", "File"],
    start: "Translate a book",
    more: "How it works",
    note: "A thesis and a ten-volume set of manuals go through exactly the same steps.",
  },

  demo: {
    file: "api-reference-v4.docx",
    place: "section 7 · 218 of 1,240",
    number: "#",
    source: "Source",
    target: "Translation",
    check: "Checks",
    verdicts: {
      checked: "Checked",
      memory: "From memory",
      term: "Glossary",
      numbers: "Numbers",
    },
    segments: SEGMENTS,
    foot: "The edit to segment 216 propagated to 39 identical places",
  },

  outcomes: {
    title: "What you get",
    lead: "Not “text in another language”, but a book ready to work with: in its own format, with your own terminology and a clear list of the places worth re-reading.",
    items: [
      {
        icon: "📖",
        title: "The same file, another language",
        text: "DOCX, EPUB and HTML are rewritten in place: formatting, images, tables, the table of contents and styles all stay where they were. Nothing to lay out again.",
      },
      {
        icon: "🗂",
        title: "One terminology across the book",
        text: "Terms are settled before translation and hold in every chapter and every volume of a series. Not “housing” in chapter 2 and “casing” in chapter 7.",
      },
      {
        icon: "🧪",
        title: "You can see what to re-read",
        text: "Every segment passes six checks. Anything doubtful is flagged and collected into its own queue — there is no need to proofread the book front to back.",
      },
    ],
  },

  steps: {
    eyebrow: "How it works",
    title: "Six steps instead of one",
    lead: "What separates this from ordinary machine translation is what happens before and after the translation itself. That is where the mistakes live that a reader finds first.",
    items: [
      {
        icon: "📥",
        title: "You upload the book",
        text: "PDF, DOCX, EPUB, HTML, Markdown or plain text. The document is broken into segments — headings, paragraphs, list items, table cells — and its structure is remembered.",
      },
      {
        icon: "🗂",
        title: "You settle the terms",
        text: "The system collects what repeats through the book and shows it as a list. You decide once; while undecided words remain, translation does not start.",
      },
      {
        icon: "🔍",
        title: "Unfamiliar words look themselves up",
        text: "An unclear word comes back with a reference: a definition, the translation accepted in the field, the expansion of an abbreviation and the addresses of the sources. What is found stays in your catalogue.",
      },
      {
        icon: "🤖",
        title: "Translation under constraints",
        text: "The model receives the segment, the paragraphs around it, the section heading and the glossary terms — as a requirement, not as a hint. Repetitions and memory matches are not translated again.",
      },
      {
        icon: "🧪",
        title: "Checks and edits",
        text: "Numbers, units, placeholders, glossary usage, abbreviation expansion. An edit to one segment propagates to all of its repetitions; a human signs the work off.",
      },
      {
        icon: "📦",
        title: "You collect the book",
        text: "A finished file in the same format. An unfinished document is never handed over silently — you see how many blocks were left as source text.",
      },
    ],
  },

  terminology: {
    eyebrow: "Terminology",
    title: "Agree first, translate second",
    lead: "A word left to the model’s discretion will be called several different things across forty places in the book — and the text will still read smoothly, so only the reader will notice. That is why the list of everything that repeats is collected up front and settled once.",
    points: [
      {
        icon: "🚦",
        strong: "Translation will not start",
        rest: " while undecided words remain on the list. You can override that, but it is a deliberate step.",
      },
      {
        icon: "🔍",
        strong: "Unfamiliar words are looked up online",
        rest: " — with a definition, the accepted translation and the addresses of the sources.",
      },
      {
        icon: "♻️",
        strong: "Once for all your work.",
        rest: " Having found out what basis risk is, you know it in the next book as well, and a year from now.",
      },
      {
        icon: "🧾",
        strong: "You decide.",
        rest: " What is found is a suggestion, not a requirement for the translation.",
      },
    ],
    candidates: "Glossary candidates",
    candidatesCount: "5 of 187",
    candidateList: CANDIDATES,
    entryTerm: "базисный риск",
    entryTarget: "basis risk",
    entryBadge: "reference from the catalogue",
    entryText:
      "The risk that the price of the underlying asset and the price of the derivative diverge while hedging: the basis moves, and the hedge stops being complete.",
    entrySource: "The source is saved together with the decision",
  },

  audience: {
    eyebrow: "Who needs this",
    title: "For students and for serious companies",
    lead: "The task is the same: terms must hold, numbers must not drift, and the file must open exactly as it was. Only the volume differs, and how many people work on it.",
    items: [
      {
        icon: "🎓",
        title: "Students and researchers",
        lead: "A textbook, a monograph, a paper, a thesis, a single chapter.",
        points: [
          "The terms of your field are settled once and hold across the whole work",
          "Formulas, notation and references to sources do not drift",
          "A reference for every unfamiliar word — with the address it came from",
          "Spending is visible for every run: no surprises at the end",
        ],
      },
      {
        icon: "🏭",
        title: "Companies and translation agencies",
        lead: "Volumes of documentation, series of manuals, product localisation.",
        points: [
          "One terminology across every volume and every translator",
          "Translation memory: the second volume of a series costs less than the first",
          "Roles, access control and isolation of each client’s data",
          "A report per document: what memory covered, what went to the model, what it cost",
        ],
      },
    ],
  },

  quality: {
    eyebrow: "Quality",
    title: "Six checks on every segment",
    lead: "The checks do not judge style — they catch what is expensive in a technical book and invisible while reading it.",
    checks: [
      "Numbers, units and notation — both the lost and the invented",
      "Placeholders and inline markup: {0}, %s, tags",
      "Glossary terms used in the required form",
      "Abbreviations expanded on first use in the document",
      "Untranslated fragments: a translation identical to its source",
      "An empty translation where the source has text",
    ],
    features: [
      {
        icon: "🧠",
        title: "Translation memory",
        text: "Repetitions inside the book and matches with earlier orders are filled in without calling the model. The same thing reads the same way.",
      },
      {
        icon: "✍️",
        title: "One edit reaches every repetition",
        text: "Fix a warning once and you have fixed it in all forty places — except the ones a human has already accepted.",
      },
      {
        icon: "🔗",
        title: "A source behind every decision",
        text: "The address where the term was looked up is saved together with the decision. An argument about a term does not start from scratch a month later.",
      },
    ],
  },

  formats: {
    eyebrow: "Formats",
    title: "A book comes back a book",
    lead: "EPUB is not text, it is an archive: cover, styles, fonts, images, manifest and table of contents. You cannot rebuild that out of translated paragraphs, so the original is rewritten in place and everything else is carried over untouched.",
    note: "Any format can be collected as plain text, as Markdown or as a new Word document — to proofread in your usual editor, for instance.",
    columns: { format: "Format", input: "Input", output: "Output" },
    accepted: "accepted",
    inPlace: "rewritten in place",
    asWord: "new Word document",
    asText: "Markdown or text",
    plainText: "text",
  },

  price: {
    eyebrow: "Cost",
    title: "You can see what you paid for",
    lead: "Every run reports back: how many segments were covered by memory and repetitions, how many went to the model and what that came to. Tokens are stored, not money: prices change, and what was spent on this book is a historical fact.",
    note: "The same warning occurring forty times is translated once — not to save money, but so that it reads the same way throughout the book. Paying for it once is a pleasant consequence.",
    bill: [
      { name: "Segments in the book", value: "12,480" },
      { name: "Covered by memory and repetitions", value: "3,902" },
      { name: "Sent to the model", value: "8,578" },
      { name: "Read from cache — a tenth of the price", value: "1.9M tokens" },
    ],
    total: "Estimated cost of the run",
  },

  faq: {
    title: "Frequently asked questions",
    items: [
      {
        q: "Will this replace a translator?",
        a: "No, and it does not try to. The machine covers what a human does slowly and with mistakes: keeping terms identical across eight hundred pages, reconciling numbers and units, filling in repetitions. The decision on anything doubtful stays with the human, and the work counts as done only once they have accepted it.",
      },
      {
        q: "What happens to formulas, notation and part numbers?",
        a: "They are carried over unchanged — that is a separate translation rule and a separate check on the output. Notation (σ, σᵤ, LT1) can be entered into the glossary as entries of its own: a substituted subscript does not read like a typo, it changes what the formula means.",
      },
      {
        q: "We have our own glossary. Can we upload it?",
        a: "Yes: CSV, TSV, TBX and working terminology registers in DOCX. What you upload never overwrites what a human entered — those rows end up in the skipped list with a reason instead of disappearing silently.",
      },
      {
        q: "How long does a book take?",
        a: "The longest part is not the translation, it is deciding on the terms — that is human work, and speeding it up at the cost of quality is pointless. The translation itself runs in batches of segments; repetitions and memory matches are not recomputed at all.",
      },
      {
        q: "What about confidentiality?",
        a: "Organisations are isolated from one another at the data model level, not in interface settings. The external reference lookup is off by default — it goes out to the internet. The translation provider is a setting, including a model you host yourself where the text must not leave your perimeter.",
      },
      {
        q: "Can we translate a single chapter?",
        a: "Yes. A document is translated in parts, and a repeat run does not touch what you have already edited and accepted. Translation memory accumulates as you go — the next chapter and the next book come out cheaper and more consistent.",
      },
    ],
  },

  cta: {
    title: "Start translating",
    lead: "Send us a book or a manual — we will set up a workspace, parse the document and show you the list of terms before a single cent is spent.",
    register: "Sign up",
    again: "Walk me through it once more",
  },

  auth: {
    promise: "Translation you can check line by line",
    points: [
      { icon: "🗂", text: "Terms are settled before translation and hold across the book" },
      { icon: "🧪", text: "Six checks on every segment: numbers, units, terms" },
      { icon: "📦", text: "DOCX, EPUB and HTML come back in their own format" },
    ],
    isolation: "Workspace data is isolated between organisations.",
    trouble: "Trouble signing in?",
    otherLanguage: "Русская версия",
  },

  form: {
    name: "Your name",
    namePlaceholder: "Alex Morgan",
    email: "Email",
    emailPlaceholder: "you@company.com",
    password: "Password",
    passwordPlaceholder: "Your password",
    passwordHint: "At least {n} characters",
    workspace: "Workspace",
    workspacePlaceholder: "Acme Translations",
    workspaceHint:
      "Projects, glossaries and the reference catalogue belong to it. You can invite colleagues later.",
    busy: "One moment…",
    failed: "That did not work. Please try again.",
    offline: "The network is unavailable. Check your connection.",
  },

  login: {
    metaTitle: "Sign in — BookTranslate",
    metaDescription: "Sign in to your BookTranslate workspace.",
    title: "Welcome back",
    lead: "The review queue is waiting exactly where you left it.",
    footerText: "No workspace yet?",
    footerLink: "Sign up",
    submit: "Sign in",
  },

  register: {
    metaTitle: "Sign up — BookTranslate",
    metaDescription: "Create a BookTranslate workspace.",
    title: "Let us set up a workspace",
    lead: "Projects, glossaries and the reference catalogue belong to it. You can invite colleagues later.",
    footerText: "Already working here?",
    footerLink: "Sign in",
    submit: "Create workspace",
    sentTitle: "Request sent",
    sentText:
      "Access is opened by an administrator. As soon as your request is approved, you sign in with the same email and password — on the sign-in page.",
  },

  join: {
    metaTitle: "Invitation — BookTranslate",
    metaDescription: "Accept an invitation to a workspace.",
    footerText: "Already working here?",
    footerLink: "Sign in",
    noTokenTitle: "The link is incomplete",
    noTokenLead: "There is no invitation key in the address.",
    noTokenText:
      "Open the whole link from the email — it is long, and mail clients sometimes break it across two lines.",
    failedTitle: "The invitation did not open",
    failedLead: "The service is unavailable. Please try again in a minute.",
    failedText:
      "Ask whoever invited you to issue the invitation again — in the “Team” section of their workspace.",
    title: "You are invited to “{org}”",
    lead: "{who} invites you as {role}. The invitation was sent to {email}.",
    owner: "The workspace owner",
    wrongAccountTitle: "You are signed in as {email}",
    wrongAccountText:
      "The invitation was issued to {email}. Sign out and open the link again — under the address it was sent to.",
    accept: "Accept the invitation",
    hasAccountTitle: "You already have an account",
    hasAccountText:
      "Sign in as {email} and open the link from the email once more — the invitation is then accepted with a single click.",
    emailHint: "The invitation was issued to this address — it cannot be changed here.",
    acceptAndEnter: "Accept and sign in",
  },

  roles: {
    owner: "an owner",
    admin: "an administrator",
    manager: "a manager",
    translator: "a translator",
    reviewer: "a reviewer",
    viewer: "a viewer",
  },
};
