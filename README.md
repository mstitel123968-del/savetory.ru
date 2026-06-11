

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
