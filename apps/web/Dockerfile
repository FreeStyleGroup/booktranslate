# Витрина в контейнере — для выката на свой сервер рядом с API.
# На Vercel этот файл не участвует: там сборка своя.
#
# Node 22 — та же версия, что в CI (.github/workflows/ci.yml): сборка,
# которую проверяли, и сборка, которая едет в бой, обязаны совпадать.

# ── Зависимости ──
FROM node:22-alpine AS deps

WORKDIR /app

COPY package.json package-lock.json ./

# npm ci, а не install: рассинхрон package.json и lock-файла обязан валить
# сборку, а не молча ставить другие версии.
RUN npm ci

# ── Сборка ──
FROM node:22-alpine AS build

WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_API_URL здесь намеренно не задан: браузер к API не обращается
# — все запросы идут через сервер витрины по внутреннему адресу API_URL,
# а он задаётся при запуске, не при сборке. Один образ годится для любого
# адреса API.
RUN npm run build

# ── Запуск ──
FROM node:22-alpine AS run

WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

# Не от root: витрина принимает данные от кого угодно.
RUN addgroup -S app && adduser -S app -G app

# Самодостаточная сборка (output: "standalone" в next.config.ts): сервер и
# ровно те модули, что ему нужны. Статика в неё не входит и копируется
# рядом — иначе страница откроется без стилей и скриптов.
COPY --from=build --chown=app:app /app/.next/standalone ./
COPY --from=build --chown=app:app /app/.next/static ./.next/static
# Файлы, отдаваемые как есть (иконки для манифеста), в сборку тоже не
# входят — без этой строки манифест ссылался бы на несуществующие картинки.
COPY --from=build --chown=app:app /app/public ./public

USER app

EXPOSE 3000

# Главная — статическая страница без походов в API: проверяется сам
# процесс, а не связь с бэкендом, у него своя проверка.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:3000/ || exit 1

CMD ["node", "server.js"]
