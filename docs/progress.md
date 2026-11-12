# Журнал виконання

Що зроблено на кожному етапі, як це перевірено і що варто памʼятати далі.

## Статус

| Етап | Назва | Статус | Дата | Коміт |
|---|---|---|---|---|
| S0 | Каркас репозиторію | done | 2026-11-12 | `c7abf61` |
| S1 | PostgreSQL: схема, сід, ролі | done | 2026-11-12 | `c8e78de` |
| S2 | RabbitMQ і worker | done | 2026-11-12 | `3a68305` |
| S3 | Generator, сценарії, сторінка керування | — | | |
| S4 | Авторизація і gateway | — | | |
| S5 | Prometheus і метрики БД | — | | |
| S6 | Grafana і дашборди | — | | |
| S7 | Loki, Alloy і логи | — | | |
| S8 | Tempo, OpenTelemetry і трейси | — | | |
| S9 | Наскрізні сценарії та повний прогін | — | | |
| S10 | Здача: README, звіт, сценарій показу | — | | |

Статуси: `—` (не розпочато) · `in progress` · `done (очікує ручної перевірки)` · `done` · `blocked`.

## Запити на зміну плану

_Формат: що не сходиться → мінімальна зміна → які етапи й тести зачепить. Процедура — `docs/00-common.md` §9._

### Запит 1 — dev-порт PostgreSQL · 2026-11-12 · **схвалено**
- **Що не сходиться:** на робочій машині `127.0.0.1:5432` зайнятий локальним PostgreSQL, тому `make up-dev` не може опублікувати Postgres стенда на 5432 (§6.1), і S1-AC7 невиконуваний.
- **Зміна:** у dev-режимі Postgres стенда публікується на `127.0.0.1:15432`; порт усередині мережі compose лишається 5432. Змінено §6.1, вимогу 10 і S1-AC7 етапу S1.
- **Зачіпає:** `docker-compose.dev.yml` (S1), таблицю портів у README (S10). Тестів не зачіпає: вони ходять усередині мережі.
- **Рішення:** обрано варіант «dev-порт 15432».

### Запит 2 — тип блокування рахунків у worker · 2026-11-12 · **вирішено**
- **Що не сходиться:** S2-AC8 не проходив. Коли всі `MAX_ATTEMPTS` спроби переказу завершувались deadlock, окрема транзакція запису `failed` теж потрапляла у взаємне блокування: перевірка зовнішнього ключа `transfers → accounts` бере `FOR KEY SHARE`, а він конфліктує з `FOR UPDATE` інших переказів. Помилка 40P01 виходила з процесора, повідомлення йшло в `transfers.dead`, і переказ губився (11 випадків з 40 у прогоні).
- **Зміна:** рахунки блокуються `SELECT … FOR NO KEY UPDATE` — це саме той рядковий лок, який бере `UPDATE` неключових колонок. Він сумісний із `KEY SHARE`, тож запис невдачі більше не чекає на перекази, а два перекази тих самих рахунків, як і раніше, блокують один одного (сценарій `deadlocks` працює). Змінено §2 і вимогу 6 етапу S2.
- **Зачіпає:** лише `services/worker/bank_worker/processor.py`. Тести не змінюються.

## Записи

_Один запис на кожен запуск етапу, нові — в кінець._

### S0 — Каркас репозиторію · 2026-11-12
- **Результат:** done
- **AC:** S0-AC1 ✅ · S0-AC2 ✅ · S0-AC3 ✅ · S0-AC4 ✅ · S0-AC5 ✅ · S0-AC6 ✅ · S0-AC7 ✅ · S0-AC8 ✅
- **Зміни:** `.gitignore`, `.env.example`, `Makefile`, `pyproject.toml`, `docker-compose{,.dev}.yml`, `README.md`; пакет `services/common/bankmon_common` (`config`, `logging`, `metrics`); `tests/` (образ, юніт-тести, e2e-каркас); `scripts/check_images.sh`, `scripts/check_ports.sh`.
- **Відхилення від плану:** немає.
- **Нотатки:**
  - Версії пакетів (PyPI, 2026-11-12): `pytest==9.2.0`, `requests==2.34.2`, `ruff==0.17.4`, `prometheus-client==0.26.0`. Ту саму версію `prometheus-client` закріплено в `services/common/pyproject.toml` — сервіси мають брати її звідти.
  - Ruff 0.17 типово форматує й Python-блоки всередині `*.md` (підтверджено `ruff config include`), тому в `pyproject.toml` перелік файлів обмежено: `include = ["*.py", "**/pyproject.toml"]`. Інакше `make lint` падає на фрагментах коду в `docs/`.
  - pytest 9.2 підміняє `sys.stdout` окремо для кожної фази тесту: потік, який обробник логів захопив під час setup фікстури, до тіла тесту вже закритий (`I/O operation on closed file`). Тому юніт-тести логування пишуть у буфер через `handler.setStream`, а запис саме в stdout перевіряє окремий тест, що викликає `setup_logging` у тілі. Те саме стосуватиметься будь-якого тесту, що налаштовує логування у фікстурі.
  - `log_event(logger, level, event, msg, /, **fields)` — перші чотири параметри лише позиційні, тож додаткове поле з назвою `level` чи `msg` не ламає виклик, а просто відкидається форматером. `exc_info=True` серед полів прикріплює виняток (`exc_type`, `exc_message`, `stack`).
  - `tests/e2e` — пакет (є `__init__.py`), `tests/` — ні. В e2e-тестах помічники імпортуються відносно: `from .helpers import wait_until`.
  - `make up` до появи першого сервісу стенда завершується `no service selected` — очікувано.
  - `scripts/check_images.sh` перевіряє не лише існування образу, а й збірку під архітектуру Docker-хоста (тут `arm64`); прогін триває близько двох хвилин.
  - `scripts/check_ports.sh` перевірено і на порушнику: контейнер-пустушка з міткою проєкту й опублікованим портом дає `PORTS FAIL`, така сама з міткою `gateway` — `PORTS OK`. У dev-режимі скрипт свідомо падає.
  - `make fmt` запускає образ `bankmon-tests` напряму з томом на запис і від імені користувача хоста.

### S1 — PostgreSQL: схема, сід, ролі · 2026-11-12
- **Результат:** done
- **AC:** S1-AC1 ✅ · S1-AC2 ✅ · S1-AC3 ✅ · S1-AC4 ✅ · S1-AC5 ✅ · S1-AC6 ✅ · S1-AC7 ✅
- **Зміни:** `db/init/01-schema.sql`, `02-seed.sql`, `03-roles.sh`; сервіс `postgres` і підключення тестів до БД у `docker-compose.yml`; dev-порт у `docker-compose.dev.yml`; `tests/e2e/helpers.py` (`db`, `check_invariants`), `conftest.py` (очікування готовності), `test_s01_db.py` (43 тести).
- **Відхилення від плану:** dev-порт PostgreSQL — `127.0.0.1:15432` за схваленим запитом 1. `check_invariants` має необовʼязковий параметр `conn`: так тест доводить, що перевірка справді ловить порушення I1, I2, I4 усередині транзакції, яку потім відкочено.
- **Нотатки:**
  - Версія пакета (PyPI, 2026-11-12): `psycopg[binary]==3.3.8`. Сервісам S2–S3 брати саме її.
  - Для колонок `GENERATED ALWAYS AS IDENTITY` ролі `bank_app` не потрібне право на послідовність — `INSERT` в `accounts` від її імені проходить (тест `test_s01_ac4_app_reads_and_writes_all_tables`).
  - У PostgreSQL 15+ у PUBLIC уже немає права `CREATE` на схему `public`, тому `CREATE TABLE` від `bank_app` забороняється без окремого `REVOKE` (`permission denied for schema public`).
  - psycopg 3 передає параметри окремо від тексту запиту, тож у `pg_stat_activity.query` видно `$1`, а не значення. Якщо тест шукає свій запит у `pg_stat_activity`, маркер треба вписувати в сам текст SQL.
  - `check_invariants()` без аргументу працює в окремому зʼєднанні з рівнем REPEATABLE READ — усі чотири перевірки бачать один знімок навіть під навантаженням.
  - Healthcheck має `start_interval: 1s`: після `make clean && make up` контейнер стає `healthy` приблизно за 2 с.
  - Префікс логу працює: рядки мають вигляд `2026-11-11 23:46:57.331 UTC [1] bank_app@bank ERROR: …` — на це спиратимуться запити Loki в S7.
  - У базовому режимі `docker compose port postgres 5432` друкує `invalid IP:0` з кодом 0 — так compose повідомляє, що порт не опубліковано. Доказ для R7 — `make check-ports` → `PORTS OK`.
  - `make check-ports` у dev-режимі свідомо падає (`postgres: 127.0.0.1:15432->5432/tcp`).
  - `make e2e` тричі поспіль: 47 passed щоразу; після `docker compose restart postgres` одразу `make e2e K=s01` → 43 passed (фікстура дочікується бази).

### S2 — RabbitMQ і worker · 2026-11-12
- **Результат:** done
- **AC:** S2-AC1 ✅ · S2-AC2 ✅ · S2-AC3 ✅ · S2-AC4 ✅ · S2-AC5 ✅ · S2-AC6 ✅ · S2-AC7 ✅ · S2-AC8 ✅ · S2-AC9 ✅ · S2-AC10 ✅ · S2-AC11 ✅ · S2-AC12 ✅ · S2-AC13 ✅ · S2-AC14 ✅
- **Зміни:** `bankmon_common.{db,amqp,messages}`; сервіс `services/worker` (`processor`, `consumer`, `settings`, `metrics`, `main`, Dockerfile); `rabbitmq` і `worker` у compose; тести `tests/unit/test_{messages,lock_order}.py`, `tests/e2e/test_s02_worker.py`, `tests/outage/`; `scripts/check_json_logs.sh`.
- **Відхилення від плану:** блокування `FOR NO KEY UPDATE` замість `FOR UPDATE` (запит 2). Інше — у нотатках.
- **Нотатки:**
  - Версія пакета (PyPI, 2026-11-12): `pika==1.4.4`. `psycopg[binary]==3.3.8` і `prometheus-client==0.26.0` — як раніше. Генератору (S3) брати ті самі.
  - `processed_at` worker записує як `clock_timestamp()`, а не типовим `now()`: `now()` — це початок транзакції, і паузи сценаріїв (`pg_sleep`) не потрапили б у різницю `processed_at - requested_at`. На цьому тримається S2-AC7.
  - Дублікати захищені двічі: перевірка `SELECT 1 FROM transfers` на початку і перехоплення `UniqueViolation` на `transfers_pkey` (два однакові повідомлення часто обробляються двома потоками одночасно). Запис `failed` використовує `ON CONFLICT DO NOTHING RETURNING id`.
  - Втрата з'єднання з БД посеред повідомлення: без `ack`, обидва з'єднання закриваються, повідомлення повертається в чергу, потік перепідключається. Відрізняється від помилки SQL перевіркою `conn.closed or conn.broken`.
  - `bank_worker_db_errors_total` рахує й очікувані помилки (40P01, 23514) — для панелі «Помилки БД за кодом SQLSTATE». Подія логу `db_error` пишеться лише для неочікуваних.
  - Серії `bank_transfers_processed_total` для `completed/none`, `failed/insufficient_funds`, `failed/deadlock` і `bank_transfer_retries_total{reason="deadlock"}` створюються одразу з нулем — щоб алерти й панелі не мали «дірок».
  - Тести S2 написано з розрахунку на фонове навантаження з S3: перевірки через рядки своїх переказів; лічильник `failed/insufficient_funds` перевіряється як «зріс щонайменше на 1». Лічильники дублікатів і мертвих повідомлень — точно, бо генератор таких не створює.
  - Статистика API керування RabbitMQ запізнюється до 5 с. Для живих даних (готові повідомлення, кількість споживачів) є `queue_counts()` — пасивне оголошення черги через AMQP.
  - Сервіс `tests` свідомо не залежить від `worker`: інакше `docker compose run tests` запускав би зупинений worker і ламав тест збою.
  - Тест збою S2-AC11 — дві фази в `tests/outage/test_s02_redelivery.py`; спільний `transfer_id` передається змінною середовища, бо репозиторій у контейнері тільки для читання, а том `tests_state` з'явиться лише в S9:
    `id=$(uuidgen | tr A-Z a-z)`; `docker compose stop worker`; `docker compose --profile test run --rm -e S02_TRANSFER_ID=$id tests pytest tests/outage/test_s02_redelivery.py -k publish_while_down`; `docker compose start worker`; те саме з `-k processed_after_start`.
  - Заміри: S2-AC8 (40 зустрічних переказів у режимі naive) ≈ 26 с; після `restart rabbitmq` S2-AC2 зелений за 3 с, після `restart postgres` — за 2 с, `RestartCount` worker = 0; `docker compose stop worker` — 0,2 с, код 0; `scripts/check_json_logs.sh worker` → `JSON LOGS OK (worker, 200)`.
