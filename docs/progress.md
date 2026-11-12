# Журнал виконання

Що зроблено на кожному етапі, як це перевірено і що варто памʼятати далі.

## Статус

| Етап | Назва | Статус | Дата | Коміт |
|---|---|---|---|---|
| S0 | Каркас репозиторію | done | 2026-11-12 | `c7abf61` |
| S1 | PostgreSQL: схема, сід, ролі | done | 2026-11-12 | `c8e78de` |
| S2 | RabbitMQ і worker | done | 2026-11-12 | `3a68305` |
| S3 | Generator, сценарії, сторінка керування | done | 2026-11-12 | `5aecd41` |
| S4 | Авторизація і gateway | done | 2026-11-12 | `9522066` |
| S5 | Prometheus і метрики БД | done | 2026-11-12 | `61d5432` |
| S6 | Grafana і дашборди | done | 2026-11-12 | `8d25510` |
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

### Запит 3 — домашній дашборд Grafana · 2026-11-12 · **вирішено**
- **Що не сходиться:** S6 вимагає домашній дашборд `bank-overview`. У Grafana 13 `default_home_dashboard_path` показує не наш дашборд, а окрему віртуальну копію з uid `default-home-dashboard`, і роль `Viewer` отримує на ній `403`. Provisioning налаштувань організації Grafana не має.
- **Зміна:** одноразовий сервіс `grafana-init` (образ Grafana, `curl`) після готовності Grafana виставляє `homeDashboardUID = bank-overview` через `PUT /api/org/preferences` і завершується; `gateway` залежить від нього з `service_completed_successfully`. Додано рядок у §6.1 і пояснення у вимозі 1 етапу S6.
- **Зачіпає:** `docker-compose.yml`, `tests/e2e/test_s06_grafana.py` (S6-AC5 перевіряє `homeDashboardUID` і доступ `viewer`).


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

### S3 — Generator, сценарії, сторінка керування · 2026-11-12
- **Результат:** done
- **AC:** S3-AC1 ✅ · S3-AC2 ✅ · S3-AC3 ✅ · S3-AC4 ✅ · S3-AC5 ✅ · S3-AC6 ✅ · S3-AC7 ✅ · S3-AC8 ✅ · S3-AC9 ✅ · S3-AC10 ✅ · S3-AC11 ✅ · S3-AC12 ✅ · S3-AC13 ✅ · S3-AC14 ✅ · S3-AC15 ✅ · S3-AC16 ✅
- **Зміни:** `bankmon_common.http`; сервіс `services/generator` (`scenarios`, `state`, `engine`, `operations`, `probe`, `api`, `metrics`, `main`, `static/control.html`); сервіс `generator` у compose, `make scenario`, `scripts/scenario.sh`; юніт-тести сценаріїв, стану, API, темпу; `tests/e2e/test_s03_generator.py`; фікстури `scenario` і `paused_generator`.
- **Відхилення від плану:** у `Scenario` додано поле `expected_alerts` — з нього сторінка керування показує очікувані алерти (§11), тож таблиця сценаріїв лишається єдиним джерелом.
- **Нотатки:**
  - Версії (PyPI, 2026-11-12): `fastapi==0.162.5`, `uvicorn==0.54.0`, `httpx==0.28.1` (тягне `starlette` 1.10). Starlette 1.10 попереджає, що `TestClient` на `httpx` застарів і радить `httpx2` — це лише попередження в юніт-тестах, пакета поза списком не додавав.
  - `PUT /control/api/state` спершу перевіряє тіло, потім пише `scenario_state`, і лише тоді змінює стан у пам'яті: `200` означає, що worker отримає нові налаштування; база недоступна → `503`, нічого не змінено.
  - Генератор переписує рядок `scenario_state` під час кожного (пере)підключення свого циклу — після рестарту БД рядок узгоджується зі станом генератора.
  - `deposit` бере рахунок із найменшим балансом через `FOR NO KEY UPDATE SKIP LOCKED`: рахунок, заблокований переказом, пропускається, і генератор не чекає.
  - uvicorn запускається з `log_config=None`, тож і його рядки йдуть у JSON через наш обробник.
  - Сторінка керування збирається з таблиці `SCENARIOS` (заглушка `<!-- SCENARIO_BUTTONS -->` у HTML); запити — на відносний `api/state`, тож працює і напряму, і за gateway.
  - **Виправлення тесту S2-AC8.** Під фоновим навантаженням тест падав: кожен потік worker кешує `scenario_state` до 1 с і перечитує лише на наступному повідомленні, тож зайнятий потік ще секунду працює за старими налаштуваннями, а пробний «повільний» переказ міг бути повільним через звичайне очікування блокування. Тепер `worker_settings` після зміни рядка чекає `SETTINGS_CACHE_S + 0,2 с` — межа випливає з контракту (§6.6). Перевірено тричі поспіль під навантаженням.
  - Для вимірювань є помічники з фіксованим вікном (`measurement_window`, `counter_deltas`, `rate_of`, `sample_for`) — це вікно спостереження, а не очікування умови; `time.sleep` як і раніше лише в `helpers.py`.
  - Фікстура сесії скидає генератор на старті лише тоді, коли він не в типовому стані, — щоб S3-AC12 перевіряв стан, у якому генератор сам піднявся після рестарту.
  - Заміри: повний `make e2e` — 78 passed за ≈4 хв; після `restart postgres` / `restart rabbitmq` лічильник операцій зростає знову за 3–4 с, `RestartCount` = 0; після рестарту посеред `deadlocks` генератор і `scenario_state` у `normal`.
  - Ручна перевірка (браузер, dev-режим, `127.0.0.1:8002/control/`): стан оновлюється, активна картка підсвічується, відлік автоповернення йде, «Пауза»/«Продовжити» працюють, при 390 px немає горизонтальної прокрутки, помилок у консолі немає.

### S4 — Авторизація і gateway · 2026-11-12
- **Результат:** done
- **AC:** S4-AC1 ✅ · S4-AC2 ✅ · S4-AC3 ✅ · S4-AC4 ✅ · S4-AC5 ✅ · S4-AC6 ✅ · S4-AC7 ✅ · S4-AC8 ✅ · S4-AC9 ✅ · S4-AC10 ✅ · S4-AC11 ✅ · S4-AC12 ✅ · S4-AC13 ✅ · S4-AC14 ✅ · S4-AC15 ✅ · S4-AC16 ✅
- **Зміни:** сервіс `services/auth` (`security`, `users`, `api`, `metrics`, `main`, `templates/login.html`); `gateway/nginx.conf`; `auth` і `gateway` у compose (єдина секція `ports`); юніт-тести безпеки, користувачів, API; `tests/e2e/test_s04_auth.py`; помічники `gateway()`, `login()`, `token()`.
- **Відхилення від плану:** немає.
- **Нотатки:**
  - Версії (PyPI, 2026-11-12): `bcrypt==5.0.0`, `PyJWT==2.15.1`, `python-multipart==0.0.33`. bcrypt 5 сам відмовляє паролям понад 72 байти — API відповідає на них `422` ще до хешування.
  - PyJWT перевіряє, що `iat` не в майбутньому: токен «з 2030 року» він відкидає (на цьому впав перший варіант юніт-тесту).
  - Gateway звертається до сервісів через змінні (`set $auth_upstream …`) і `resolver 127.0.0.11`: nginx стартує, навіть коли сервіс ще не піднявся, і знаходить контейнер із новою IP після перестворення (замість граблі G13). З такою формою `proxy_pass` URI передається як є, тож у підзапиті перевірки шлях `/auth/verify?require=admin` записано повністю.
  - Підзапит `auth_request` іде методом `GET` (`proxy_method GET`): інакше для `PUT /control/api/state` він теж був би `PUT`, маршрут `/auth/verify` відповів би `405`, а nginx — `500`.
  - Заголовки `X-Auth-User` і `X-Auth-Role` задано на рівні `server` змінними з відповіді `auth`; порожнє значення означає, що заголовок не передається взагалі — тому клієнтський `X-Auth-User` до сервісів не доходить (S4-AC10). Важливо для S6: локація з власними `proxy_set_header` не успадковує серверні — там їх треба повторити.
  - `absolute_redirect off` — інакше nginx писав би в `Location` повну адресу з внутрішнім іменем хоста.
  - `rd` у перенаправленні на вхід передається як є (`$request_uri`): у nginx без модулів немає URL-кодування. Для шляхів без `&` у рядку запиту цього досить.
  - `/auth/verify` на невідоме значення `require` відповідає `400`, а не пропускає: помилка в конфігурації gateway дасть `500`, а не відкритий доступ.
  - Журнал доступу gateway — JSON (`ts` з мілісекундами зібрано з `$time_iso8601` і `$msec`); 9 рядків банера `docker-entrypoint.sh` на старті — не JSON, це нормально.
  - Помічник `GatewaySession.get` перевизначено: `requests.Session.get` сам передає `allow_redirects=True`, і тести йшли за перенаправленнями.
  - Ручна перевірка (браузер, `localhost:8080`): без входу `/control/` → форма входу; невірний пароль → `401`, «Невірний логін або пароль», логін лишився в полі; вхід `admin` → сторінка керування (`rd` збережено й після невдалої спроби); вихід → форма; `viewer` → `/control/` `403`. Наприкінці виконано вихід.
  - Заміри: повний `make e2e` — 102 passed за ≈4 хв 13 с; `make unit` — 148 passed.

### S5 — Prometheus і метрики БД · 2026-11-12
- **Результат:** done
- **AC:** S5-AC1 ✅ · S5-AC2 ✅ · S5-AC3 ✅ · S5-AC4 ✅ · S5-AC5 ✅ · S5-AC6 ✅ · S5-AC7 ✅ · S5-AC8 ✅ · S5-AC9 ✅ · S5-AC10 ✅ · S5-AC11 ✅
- **Зміни:** `observability/prometheus/prometheus.yml`, `rules/bank.yml`; `postgres-exporter` і `prometheus` у compose (+ dev-порти 9090, 9187); маршрут `/prometheus/` у gateway; помічники `prom_*`, `alert_states`, `wait_alert`; `tests/e2e/test_s05_metrics.py`.
- **Відхилення від плану:** немає.
- **Нотатки:**
  - Підтверджено `--help` зафіксованих версій: експортер — `--collector.stat_statements` (типово вимкнений), підключення через `DATA_SOURCE_NAME`; Prometheus 3.15 — `--web.external-url`, `--web.route-prefix`, `--storage.tsdb.retention.time`, `--enable-feature=exemplar-storage`. В образах експортера й Prometheus є `wget` — healthcheck через нього (G2). Плагін `rabbitmq_prometheus` уже ввімкнений в образі.
  - `scrape_timeout: 4s` задано явно: типові 10 с більші за інтервал 5 с, і Prometheus такий конфіг відкидає.
  - Усі очікувані назви чужих метрик збіглися з фактичними (`pg_stat_activity_count`, `pg_locks_count`, `pg_settings_max_connections`, `pg_stat_user_tables_n_live_tup`, `rabbitmq_queue_*{queue=…}`); `pg_stat_statements` дає `pg_stat_statements_{calls,seconds,rows,block_read_seconds,block_write_seconds}_total`.
  - Prometheus 3 сам перенаправляє `/prometheus/` → `/prometheus/query`; UI посилається на ресурси відносно (`./assets/…`), тож вони вантажаться через `/prometheus/assets/…`.
  - **Граблі:** змонтовані конфіги не перечитуються самі. Після зміни `gateway/nginx.conf` — `docker compose restart gateway`; після зміни `prometheus.yml` чи правил — `docker compose restart prometheus`. `make up` не перестворює контейнер, якщо змінився лише вміст змонтованого файлу (у цьому етапі через це `/prometheus/` спершу віддавав 404).
  - Заміри: `TransferFailureRatioHigh` і `DeadlocksDetected` переходять у `firing` і назад у `inactive` у межах 120/150 с; у звичайному режимі за 60 с жодного алерту; зразок `up{job="worker"}` до перезапуску Prometheus читається й після; повний `make e2e` — 152 passed за ≈8 хв 21 с.
  - Ручна перевірка (браузер, `admin`): `/prometheus/targets` — усі шість цілей `UP`; `/prometheus/alerts` — 7 правил `INACTIVE`; усі запити сторінок — `200`.

### S6 — Grafana і дашборди · 2026-11-12
- **Результат:** done
- **AC:** S6-AC1 ✅ · S6-AC2 ✅ · S6-AC3 ✅ · S6-AC4 ✅ · S6-AC5 ✅ · S6-AC6 ✅ · S6-AC7 ✅ · S6-AC8 ✅ · S6-AC9 ✅ · S6-AC10 ✅ · S6-AC11 ✅ · S6-AC12 ✅
- **Зміни:** `observability/grafana/provisioning/{datasources,dashboards}/*.yml`; дашборди `bank-overview`, `bank-db`, `bank-app`, `bank-queue`; сервіси `grafana` і одноразовий `grafana-init` у compose (+ dev-порт 3000); маршрути `/grafana/` і `/grafana/api/live/` (WebSocket) у gateway; ціль `grafana` у Prometheus; експортер — `--collector.stat_statements.include_query`; помічники `grafana_api`, `dashboard_files`, `panel_exprs`; `tests/e2e/test_s06_grafana.py`.
- **Відхилення від плану:** запит 3 — домашній дашборд задає одноразовий сервіс `grafana-init` замість `default_home_dashboard_path`; експортер віддає текст запиту для таблиці «Найважчі запити».
- **Нотатки:**
  - Перевірено на образі: роль із заголовка auth proxy (`headers = Role:X-WEBAUTH-ROLE`) у Grafana 13.2.6 працює і з `sync_ttl = 0` синхронізується на кожному запиті (Admin → Viewer → Admin). Документація цю можливість лише згадує в прикладі. Перша перевірка помилково показала протилежне через розбиття слів у zsh — у скриптах перевірок передавати значення явно.
  - `default_home_dashboard_path` у Grafana 13 віддає окрему віртуальну копію з uid `default-home-dashboard`, яку `Viewer` відкрити не може (`403`). Тому домашній дашборд задається налаштуванням організації (`PUT /api/org/preferences`, `homeDashboardUID`) з одноразового контейнера; `gateway` залежить від нього з `service_completed_successfully` — `up --wait` це приймає (G17 перевірено).
  - Під підшляхом Grafana віддає метрики на `/grafana/metrics` (`/metrics` перенаправляє на `root_url`) — так і налаштовано ціль Prometheus.
  - Дашборди згенеровано скриптом (тимчасовим, поза репозиторієм) і перевірено на перекриття панелей. Показники огляду — два ряди по чотири (у ряд по вісім заголовки обрізались). Таблиця «Активні алерти» без алертів показує «Активних алертів немає» замість «No data». Вирази з рідкісними метриками закінчуються `or vector(0)`, частки — `clamp_min(…, 1e-9)` у знаменнику.
  - Grafana логує у JSON (`GF_LOG_CONSOLE_FORMAT=json`) — знадобиться в S7.
  - Ручна перевірка (браузер, `viewer`, 1440 px): після входу одразу відкривається «BankMonitor — огляд»; на всіх чотирьох дашбордах немає «No data» і помилок панелей; помилок WebSocket у консолі немає; запити `/grafana/api/ds/query` — `200`. Значення на огляді: 7 з 7 сервісів, ≈47 транзакцій/с, ≈14 переказів/с, відмов 0 %, p95 ≈ 5 мс.
  - Злиття S5 у `main` не змінювало дерева відносно перевіреної гілки, тому повний прогін на `main` після нього не повторювався; його покриває прогін S6 і `make verify` (S9).
  - **Виправлення перевірки інваріантів.** Повний прогін «зависав»: запит I4 у `check_invariants()` (`LEFT JOIN … GROUP BY t.id … LIMIT 5`) планувальник виконував вкладеним циклом transfers × ledger_entries (≈10¹⁰ порівнянь) — понад 4 хв на 74 тис. переказів. Тепер проводки спершу агрегуються за `transfer_id`, а потім з'єднуються з переказами: 88 мс. Умову обгорнуто в `COALESCE(…, false)` — без цього завершений переказ без проводок давав `NULL` і зникав з результату (це одразу зловив тест `test_s01_ac3_check_invariants_detects_violations[I4]`).
  - Заміри: повний `make e2e` — 222 passed за 8 хв 31 с.
