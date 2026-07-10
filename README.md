

## Прод-запуск

1. Отредактируйте `.env.prod`, заменив плейсхолдеры на боевые значения (секретный ключ, домены, доступы к БД и т.д.).
2. Поднимите прод-стек Docker:
   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
   ```
3. Выполните миграции базы данных:
   ```bash
   docker compose -f docker-compose.prod.yml exec web python manage.py migrate
   ```
4. Соберите статические файлы Django:
   ```bash
   docker compose -f docker-compose.prod.yml exec web python manage.py collectstatic --noinput
   ```
5. Проверьте конфигурацию Nginx:
   ```bash
   docker compose -f docker-compose.prod.yml exec nginx nginx -t
   ```

> При необходимости заполните блоки S3/MinIO и почтовых параметров в `.env.prod`.

### Подключение к PostgreSQL через DBeaver

Production-конфигурация публикует PostgreSQL только на `127.0.0.1` сервера.
Подключайтесь через встроенный SSH-туннель DBeaver, не открывая порт `5432` в
публичном firewall.

1. В `.env.prod` укажите `DB_HOST_PORT=5432` и примените конфигурацию:
   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.prod up -d db
   ```
2. В DBeaver на вкладке подключения PostgreSQL укажите:
   - Host: `127.0.0.1`
   - Port: значение `DB_HOST_PORT` (по умолчанию `5432`)
   - Database: значение `DB_NAME`
   - Username: значение `DB_USER`
   - Password: значение `DB_PASSWORD`
3. На вкладке SSH включите туннель и укажите IP сервера, SSH-пользователя и
   приватный ключ либо SSH-пароль.

Если порт `5432` уже занят на сервере, задайте, например,
`DB_HOST_PORT=15432` и используйте `15432` в DBeaver.

## Десктоп-приложение TrezoApp
Для офлайн-доступа к рубрикам и настройкам добавлен каталог `desktop_app/` с самостоятельным PySide6-приложением. Основные сведения:

- Структура проекта: исходники в `desktop_app/app/`, ресурсы в `desktop_app/resources/`, зависимости в `desktop_app/requirements.txt`.
- Приложение хранит данные локально в `%APPDATA%/TrezoApp` (Windows) либо `~/.local/share/TrezoApp` (Linux/macOS). При первом запуске создаются `rubrics.json`, `items.json`, `settings.json`.
- Интерфейс повторяет сайт: боковая панель с поиском и списком рубрик, экран архива и отдельный экран настроек. Настройки (темы, акцент, типографика, конфиденциальность, интенсивность фона) сразу сохраняются и применяются.
- Для сборки `.exe` под Windows следуйте инструкциям `desktop_app/BUILD_WINDOWS.md` (включает шаги по установке зависимостей и запуску PyInstaller).

Быстрый запуск в dev-режиме:
```bash
cd desktop_app
python -m venv venv
source venv/bin/activate  # Windows: .\\venv\\Scripts\\activate
pip install -r requirements.txt
python -m app.main
```
## Docker build TLS workaround

If `pip install -r requirements.txt` fails inside Docker with
`SSL: UNEXPECTED_EOF_WHILE_READING`, retry after Docker Desktop has a stable
network connection:

```bash
docker compose build --no-cache web
```

The Dockerfile installs CA certificates and uses longer pip retries/timeouts.
If the local network, VPN, proxy, or provider still breaks TLS to PyPI, build
with an explicit index or local proxy:

```bash
docker compose build --build-arg PIP_INDEX_URL=https://pypi.org/simple web
docker compose build --build-arg PIP_INDEX_URL=http://your-proxy/simple --build-arg PIP_TRUSTED_HOST=your-proxy web
```


## YooKassa

Платежи включаются только переменными окружения. Реальные ключи нельзя
коммитить, выводить в HTML, JavaScript или логи.

```env
YOOKASSA_SHOP_ID=
YOOKASSA_SECRET_KEY=
YOOKASSA_RETURN_URL=https://example.com/subscriptions/payment/result/
```

Для production `docker-compose.prod.yml` читает эти значения через `.env.prod`.
Для локального `docker-compose.yml` переменные пробрасываются из окружения с
безопасными пустыми значениями по умолчанию. Создание платежа доступно только
если заполнены `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY` и `YOOKASSA_RETURN_URL`.

Webhook URL для ЮKassa: `/subscriptions/yookassa/webhook/`.
Return URL для пользователя: `/subscriptions/payment/result/`.
