#!/usr/bin/env bash
# BookTranslate — установка на чистый сервер одной командой.
#
# Что делает, по порядку:
#   1. от root: обновляет систему, заводит пользователя deploy, включает
#      файрвол и fail2ban, ставит докер, чинит MTU, если интерфейс урезан;
#   2. от deploy: делает ключ для GitHub и ждёт, пока его добавят в Deploy
#      keys; клонирует репозиторий; собирает .env с секретами; входит в
#      реестр образов; поднимает compose; ждёт, пока всё станет healthy;
#      проверяет оба домена снаружи; заводит первого администратора и
#      пробует модель.
#
# Как запускать (на своей машине, потом на сервере):
#
#   scp deploy/bootstrap.sh root@<IP>:/root/
#   ssh -t root@<IP> bash bootstrap.sh
#
# 🔥 Именно «ssh -t»: без терминала скрытый ввод ключей не работает —
# read не может выключить эхо, и ключ модели с токеном GitHub окажутся на
# экране и в буфере терминала. Скрипт без терминала прерывается сам.
#
# Потом, из ВТОРОГО окна проверив, что «ssh deploy@<IP>» пускает по ключу:
#
#   ssh -t root@<IP> bash bootstrap.sh harden   # закрыть root и пароли
#
# Скрипт можно запускать повторно: что уже сделано, он пропускает.
# Значения можно передать переменными, чтобы он ничего не спрашивал, —
# но секреты так лучше не передавать: строка команды попадает в историю
# оболочки. Ключи спрашиваются с экрана и дальше живут только в .env.
#
#   WEB_DOMAIN=app.example.ru API_DOMAIN=api.example.ru ADMIN_EMAIL=… bash bootstrap.sh
#
# Требования: Ubuntu 22.04/24.04 (Debian тоже пойдёт), вход root.
# Заранее нужны: тег v<версия> в репозитории (по нему собраны образы),
# токен GitHub (classic) с правом read:packages, две A-записи на этот IP.

set -euo pipefail

REPO_SSH="git@github.com:FreeStyleGroup/booktranslate.git"
IMAGE_BASE="ghcr.io/freestylegroup/booktranslate"
GITHUB_USER_DEFAULT="FreeStyleGroup"
APP_USER="deploy"
APP_DIR="/home/$APP_USER/booktranslate"
COMPOSE="docker compose -f docker-compose.prod.yml"
# Копия скрипта, которую запускает deploy: исходный файл лежит у root, и
# читать его оттуда deploy не может.
SELF="/usr/local/sbin/booktranslate-bootstrap"

# Переменные, которые передаются из root-этапа в deploy-этап, если заданы.
FORWARDED=(WEB_DOMAIN API_DOMAIN ANTHROPIC_API_KEY ANTHROPIC_BASE_URL IMAGE_TAG
           GITHUB_USER GHCR_TOKEN ADMIN_EMAIL DOCKER_NETWORK_MTU)

# ── Вывод ──

say()  { printf '\n\033[1;36m▶ %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m✔ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m⚠ %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m✖ %s\033[0m\n' "$*" >&2; exit 1; }

# ask ПЕРЕМЕННАЯ "подсказка" [умолчание] [secret|optional]
# Уже заданную переменную окружения не переспрашивает — так скрипт
# работает и без человека у консоли.
ask() {
    local var="$1" prompt="$2" default="${3:-}" mode="${4:-}" value
    if [[ -n "${!var:-}" ]]; then return; fi
    # Без терминала read вернёт ошибку, и под set -e скрипт молча умрёт на
    # первом же вопросе — объясняем заранее, чего не хватает.
    [[ -t 0 ]] || die "Нужен терминал для вопроса «$prompt»: запускайте через «ssh -t» либо задайте $var переменной."
    while true; do
        if [[ "$mode" == secret ]]; then
            read -rsp "$prompt: " value; echo
        else
            read -rp "$prompt${default:+ [$default]}: " value
        fi
        value="${value:-$default}"
        if [[ -n "$value" || "$mode" == optional ]]; then break; fi
        warn "Пустым оставить нельзя."
    done
    printf -v "$var" '%s' "$value"
}

# ═══════════════════════════════════════════════════════════════════
# Этап 1 — система, от root
# ═══════════════════════════════════════════════════════════════════

need_root() { [[ $EUID -eq 0 ]] || die "Этот этап — от root: sudo bash $0 ${1:-}"; }

system() {
    need_root system
    command -v apt-get >/dev/null || die "Рассчитано на Ubuntu/Debian: нужен apt."

    export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a

    say "Обновление системы"
    apt-get update -q
    apt-get upgrade -yq
    apt-get install -yq curl git ufw fail2ban unattended-upgrades openssl ca-certificates
    timedatectl set-timezone Europe/Moscow 2>/dev/null || true
    ok "Пакеты обновлены"

    say "Пользователь $APP_USER"
    if ! id "$APP_USER" &>/dev/null; then
        adduser --disabled-password --gecos "" "$APP_USER"
    fi
    usermod -aG sudo "$APP_USER"
    # Вход только по ключу, пароля у deploy нет — значит, sudo спрашивать
    # его не у кого. Файл именно в sudoers.d: правка самого sudoers с
    # опечаткой закрывает sudo для всех, включая того, кто её сделал.
    echo "$APP_USER ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/$APP_USER"
    chmod 440 "/etc/sudoers.d/$APP_USER"

    install -d -m 700 -o "$APP_USER" -g "$APP_USER" "/home/$APP_USER/.ssh"
    if [[ -s /root/.ssh/authorized_keys && ! -s "/home/$APP_USER/.ssh/authorized_keys" ]]; then
        install -m 600 -o "$APP_USER" -g "$APP_USER" \
            /root/.ssh/authorized_keys "/home/$APP_USER/.ssh/authorized_keys"
        ok "Ключ root скопирован пользователю $APP_USER"
    fi
    if [[ ! -s "/home/$APP_USER/.ssh/authorized_keys" ]]; then
        warn "У $APP_USER нет SSH-ключа. Положите свой публичный ключ в" \
             "/home/$APP_USER/.ssh/authorized_keys (права 600) до команды harden."
    fi

    say "Файрвол и защита входа"
    ufw allow OpenSSH >/dev/null
    ufw allow 80/tcp >/dev/null
    ufw allow 443/tcp >/dev/null
    ufw --force enable >/dev/null
    systemctl enable --now fail2ban >/dev/null
    ok "Снаружи открыты только SSH, 80 и 443"

    say "Docker"
    if ! command -v docker >/dev/null; then
        # Из репозитория Docker, а не из apt Ubuntu: там compose старой
        # версии, без --format json и с другим разбором .env.
        curl -fsSL https://get.docker.com | sh
    fi
    usermod -aG docker "$APP_USER"
    systemctl enable --now docker >/dev/null
    ok "$(docker --version)"

    fix_mtu

    install -m 755 "$(readlink -f "$0")" "$SELF"
}

# На части хостингов (reg.ru точно) интерфейс урезан ниже 1500, и
# контейнеры с MTU по умолчанию теряют крупные пакеты: запросы к модели
# и к GitHub из контейнера зависают при живой сети хоста. Симптом
# невнятный, поэтому проверяем заранее. daemon.json задаёт MTU мосту
# docker0; сеть compose получает его через driver_opts в
# docker-compose.prod.yml — проверять после запуска: docker network
# inspect booktranslate_default.
fix_mtu() {
    local iface mtu wanted
    iface=$(ip route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i <= NF; i++) if ($i == "dev") {print $(i + 1); exit}}')
    [[ -n "$iface" ]] || return 0
    mtu=$(cat "/sys/class/net/$iface/mtu")
    (( mtu < 1500 )) || return 0

    wanted=$(( mtu - 50 ))
    if [[ -f /etc/docker/daemon.json ]]; then
        if grep -q '"mtu"' /etc/docker/daemon.json; then
            return 0
        fi
        warn "MTU интерфейса $iface — $mtu, но /etc/docker/daemon.json уже есть." \
             "Добавьте в него \"mtu\": $wanted вручную и перезапустите docker."
        return 0
    fi
    printf '{\n  "mtu": %d\n}\n' "$wanted" > /etc/docker/daemon.json
    systemctl restart docker
    # Сеть compose про daemon.json не знает — ей MTU передаётся через .env.
    export DOCKER_NETWORK_MTU="$wanted"
    ok "MTU интерфейса $mtu → докеру задан $wanted"
}

app_as_deploy() {
    local names=() name
    for name in "${FORWARDED[@]}"; do
        if [[ -n "${!name:-}" ]]; then
            export "$name"
            names+=("$name")
        fi
    done
    # Переменные уходят через --preserve-env, а не аргументами «env K=V»:
    # sudo пишет полную строку команды в журнал, и ключ модели с токеном
    # оказались бы в auth.log. Группа docker у deploy подхватывается и без
    # login-оболочки — sudo выставляет группы целевого пользователя сам.
    local keep=""
    (( ${#names[@]} )) && keep=$(IFS=,; echo "${names[*]}")
    sudo -u "$APP_USER" -H ${keep:+--preserve-env="$keep"} bash "$SELF" app
}

# ═══════════════════════════════════════════════════════════════════
# Этап 2 — приложение, от deploy
# ═══════════════════════════════════════════════════════════════════

github_reachable() {
    local out
    # ssh -T к GitHub всегда завершается кодом 1, ответ — в тексте.
    out=$(ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes -T git@github.com 2>&1 || true)
    [[ "$out" == *"successfully authenticated"* ]]
}

# set_env КЛЮЧ ЗНАЧЕНИЕ — переписать строку в .env или дописать её.
set_env() {
    local key="$1" value="$2" escaped
    escaped=$(printf '%s' "$value" | sed -e 's/[\\&|]/\\&/g')
    if grep -q "^$key=" .env; then
        sed -i "s|^$key=.*|$key=$escaped|" .env
    else
        printf '%s=%s\n' "$key" "$value" >> .env
    fi
}

read_env() { grep "^$1=" .env | head -1 | cut -d= -f2-; }

wait_healthy() {
    local service="$1" waited=0 id
    while true; do
        id=$($COMPOSE ps -q "$service" 2>/dev/null || true)
        if [[ -n "$id" && "$(docker inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null)" == healthy ]]; then
            return 0
        fi
        (( waited >= 180 )) && return 1
        sleep 5; (( waited += 5 ))
    done
}

wait_http() {
    local url="$1" waited=0
    # Сертификат выпускается в первую минуту, DNS может ещё расходиться —
    # ждём до четырёх минут, прежде чем объявить отказ.
    until curl -fsS -o /dev/null --max-time 10 "$url"; do
        (( waited >= 240 )) && return 1
        sleep 10; (( waited += 10 ))
    done
}

app() {
    [[ "$(id -un)" == "$APP_USER" ]] || die "Этот этап — от $APP_USER: sudo -iu $APP_USER bash $SELF app"
    cd "/home/$APP_USER"

    say "Ключ для GitHub"
    if [[ ! -f ~/.ssh/id_ed25519 ]]; then
        ssh-keygen -q -t ed25519 -N "" -C "booktranslate-$(hostname)" -f ~/.ssh/id_ed25519
    fi
    until github_reachable; do
        echo
        cat ~/.ssh/id_ed25519.pub
        echo
        echo "Добавьте этот ключ: GitHub → booktranslate → Settings → Deploy keys → Add deploy key."
        echo "Право записи (Allow write access) — НЕ ставить."
        [[ -t 0 ]] || die "Ключ ещё не добавлен в Deploy keys, а терминала для ожидания нет: добавьте ключ и запустите снова через «ssh -t»."
        read -rp "Нажмите Enter, когда добавили… " _
    done
    ok "GitHub пускает по ключу"

    say "Код"
    if [[ -d "$APP_DIR/.git" ]]; then
        git -C "$APP_DIR" pull --ff-only
    else
        git clone "$REPO_SSH" "$APP_DIR"
    fi
    cd "$APP_DIR"
    ok "$(git log -1 --format='%h %s')"

    say "Настройки (.env)"
    if [[ -f .env ]]; then
        warn ".env уже есть — не трогаю. Править: nano $APP_DIR/.env"
    else
        ask WEB_DOMAIN "Домен сайта — как его набирает посетитель (например booktranslate.ru)"
        ask API_DOMAIN "Домен API — отдельное имя, обычно поддомен" "api.${WEB_DOMAIN}"
        ask ANTHROPIC_API_KEY "Ключ модели — Anthropic или шлюза" "" secret
        ask ANTHROPIC_BASE_URL "Адрес шлюза; пусто — напрямую в Anthropic (AITunnel: https://api.aitunnel.ru)" "" optional
        ask IMAGE_TAG "Версия образов — тег репозитория без «v»" "0.1.0"

        cp apps/api/.env.production.example .env
        chmod 600 .env
        # Секреты только генерируются: придуманный человеком пароль базы
        # переживёт первый же чужой контейнер на этой машине.
        set_env JWT_SECRET "$(openssl rand -hex 32)"
        set_env POSTGRES_PASSWORD "$(openssl rand -hex 24)"
        set_env WEB_DOMAIN "$WEB_DOMAIN"
        set_env API_DOMAIN "$API_DOMAIN"
        # На голом домене сертификат нужен и на «www»: его набирают по
        # привычке, и без сертификата такой посетитель видит не сайт, а
        # предупреждение браузера. Перенаправление на голый домен делает
        # прокси (deploy/Caddyfile). Признак голого домена — одна точка;
        # у доменов вида example.co.uk он даст промах, там имя для
        # сертификата правится в .env руками.
        if [[ "$WEB_DOMAIN" == *.*.* ]]; then
            set_env WEB_SITE "$WEB_DOMAIN"
        else
            set_env WEB_SITE "$WEB_DOMAIN, www.$WEB_DOMAIN"
            ok "К сертификату добавлено www.$WEB_DOMAIN — нужна A-запись и на него"
        fi
        # «api» — имя сервиса: по нему витрина ходит в API внутри докера.
        set_env ALLOWED_HOSTS "[\"$API_DOMAIN\",\"api\"]"
        set_env CORS_ORIGINS "[\"https://$WEB_DOMAIN\"]"
        set_env ANTHROPIC_API_KEY "$ANTHROPIC_API_KEY"
        set_env ANTHROPIC_BASE_URL "$ANTHROPIC_BASE_URL"
        set_env API_IMAGE "$IMAGE_BASE/api:$IMAGE_TAG"
        set_env WEB_IMAGE "$IMAGE_BASE/web:$IMAGE_TAG"
        if [[ -n "${DOCKER_NETWORK_MTU:-}" ]]; then
            set_env DOCKER_NETWORK_MTU "$DOCKER_NETWORK_MTU"
        fi
        ok ".env собран, секреты сгенерированы"
    fi
    WEB_DOMAIN=$(read_env WEB_DOMAIN)
    API_DOMAIN=$(read_env API_DOMAIN)

    say "DNS"
    local my_ip domain resolved bad=0
    my_ip=$(curl -4fsS --max-time 10 https://ifconfig.me 2>/dev/null || curl -4fsS --max-time 10 https://api.ipify.org 2>/dev/null || true)
    # Проверяются все имена, на которые прокси будет просить сертификат,
    # включая «www»: запись, про которую забыли, выясняется здесь, а не
    # через час в журнале прокси.
    for domain in $(read_env WEB_SITE | tr ',' ' ') "$API_DOMAIN"; do
        resolved=$(getent ahostsv4 "$domain" 2>/dev/null | awk 'NR == 1 {print $1}')
        if [[ -n "$my_ip" && "$resolved" == "$my_ip" ]]; then
            ok "$domain → $resolved"
        else
            warn "$domain → ${resolved:-записи нет}, а этот сервер — ${my_ip:-неизвестно}"
            bad=1
        fi
    done
    if (( bad )); then
        warn "Пока домен не указывает сюда, сертификат не выпустится и сайт снаружи не откроется."
        local answer
        [[ -t 0 ]] || die "Поправьте A-записи и запустите снова: sudo -iu $APP_USER bash $SELF app"
        read -rp "Продолжить всё равно? [y/N] " answer
        [[ "$answer" =~ ^[yYдД] ]] || die "Поправьте A-записи и запустите снова: sudo -iu $APP_USER bash $SELF app"
    fi

    say "Реестр образов"
    if grep -q '"ghcr.io"' ~/.docker/config.json 2>/dev/null; then
        ok "Вход в ghcr.io уже выполнен"
    else
        ask GITHUB_USER "Логин GitHub" "$GITHUB_USER_DEFAULT"
        ask GHCR_TOKEN "Токен GitHub (classic) с правом read:packages" "" secret
        printf '%s' "$GHCR_TOKEN" | docker login ghcr.io -u "$GITHUB_USER" --password-stdin
    fi

    say "Образы"
    $COMPOSE pull || die "Образы не скачались. Есть ли в репозитории тег v$(read_env API_IMAGE | sed 's/.*://') и зелёный прогон Release в Actions? Токен — с read:packages?"

    say "Запуск"
    $COMPOSE up -d

    local service
    for service in postgres api web; do
        if wait_healthy "$service"; then
            ok "$service — healthy"
        else
            $COMPOSE logs --tail=40 "$service"
            die "$service не стал healthy за три минуты. Журнал выше; полный — $COMPOSE logs $service"
        fi
    done

    say "Снаружи"
    if wait_http "https://$API_DOMAIN/health"; then
        ok "https://$API_DOMAIN/health → $(curl -fsS "https://$API_DOMAIN/health")"
    else
        warn "API по https://$API_DOMAIN не отвечает: DNS или сертификат. Смотреть: $COMPOSE logs proxy"
    fi
    if wait_http "https://$WEB_DOMAIN/"; then
        ok "https://$WEB_DOMAIN/ отвечает"
    else
        warn "Витрина по https://$WEB_DOMAIN не отвечает. Смотреть: $COMPOSE logs proxy web"
    fi

    # Ограничитель частоты в API верит адресу посетителя только из сети
    # compose. Докер выдаёт сети из 172.17–172.31, но на занятой машине
    # может уйти в 192.168.х — тогда все посетители сольются в одного, и
    # десять неверных паролей закроют вход всем сразу.
    local subnet
    subnet=$(docker network inspect -f '{{range .IPAM.Config}}{{.Subnet}}{{end}}' "$($COMPOSE ps -q api | head -1 | xargs docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}')" 2>/dev/null || true)
    if [[ -n "$subnet" && "$subnet" != 172.* ]]; then
        warn "Сеть compose — $subnet, вне 172.16.0.0/12. Впишите её в .env: FORWARDED_ALLOW_IPS=$subnet и выполните $COMPOSE up -d api"
    fi

    say "Первый администратор"
    ask ADMIN_EMAIL "Почта администратора площадки"
    # Пароль команда спросит сама; на пустой ввод сгенерирует и покажет
    # ОДИН раз — в базе только хеш.
    $COMPOSE exec api python -m app.cli create-superuser --email "$ADMIN_EMAIL"

    say "Проверка модели"
    $COMPOSE exec api python -m app.cli check-provider \
        || warn "Модель не ответила. Ключ, шлюз и имя модели — в $APP_DIR/.env; после правки: $COMPOSE up -d api"

    cat <<EOF

$(ok "Готово")

  Витрина:        https://$WEB_DOMAIN/
  Администратор:  https://$WEB_DOMAIN/root
  Код и .env:     $APP_DIR
  Журналы:        cd $APP_DIR && $COMPOSE logs -f

Осталось от root — закрыть вход по паролю, ПОСЛЕ проверки из второго окна,
что «ssh $APP_USER@сервер» пускает по ключу:

  bash $SELF harden

EOF
}

# ═══════════════════════════════════════════════════════════════════
# Закрытие входа по паролю — отдельно и только после проверки ключа
# ═══════════════════════════════════════════════════════════════════

harden() {
    need_root harden
    [[ -s "/home/$APP_USER/.ssh/authorized_keys" ]] \
        || die "У $APP_USER нет ключа — закрывать вход по паролю нельзя, иначе на сервер никто не войдёт."

    # Не правка sshd_config, а свой файл в sshd_config.d: образы хостингов
    # кладут туда 50-cloud-init.conf с «PasswordAuthentication yes», а
    # Include стоит в начале sshd_config, и у sshd побеждает ПЕРВОЕ
    # вхождение — правка основного файла ничего бы не закрыла. Имя с «00-»
    # ставит наш файл раньше всех остальных.
    install -d -m 755 /etc/ssh/sshd_config.d
    printf 'PermitRootLogin no\nPasswordAuthentication no\nKbdInteractiveAuthentication no\n' \
        > /etc/ssh/sshd_config.d/00-booktranslate.conf
    grep -q '^Include /etc/ssh/sshd_config.d/' /etc/ssh/sshd_config \
        || sed -i '1i Include /etc/ssh/sshd_config.d/*.conf' /etc/ssh/sshd_config

    # Проверка конфигурации до перезапуска: сломанный sshd не поднимется,
    # и текущее окно станет последним.
    sshd -t
    # Верить надо не файлу, а тому, что sshd из него собрал.
    local effective
    effective=$(sshd -T 2>/dev/null | grep -Ei '^(permitrootlogin|passwordauthentication) ')
    [[ "$effective" == *"permitrootlogin no"* && "$effective" == *"passwordauthentication no"* ]] \
        || die "sshd -T показывает, что вход по паролю всё ещё разрешён: $effective"

    systemctl restart ssh 2>/dev/null || systemctl restart sshd
    ok "Вход root и вход по паролю закрыты. Дальше — только ssh $APP_USER@сервер по ключу."
}

usage() {
    cat <<EOF
Использование: bash $0 [этап]

  (без аргумента)  всё подряд: система от root, затем приложение от $APP_USER
  system           только система (root)
  app              только приложение (от $APP_USER)
  harden           закрыть вход root и по паролю (root; после проверки ключа)
EOF
    exit 2
}

case "${1:-all}" in
    all)    system; app_as_deploy ;;
    system) system ;;
    app)    app ;;
    harden) harden ;;
    *)      usage ;;
esac
