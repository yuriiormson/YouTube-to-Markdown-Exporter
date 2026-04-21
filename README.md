# YouTube to Markdown Exporter

Цей інструмент дозволяє автоматично знаходити відео на YouTube каналі за ключовим словом (наприклад, "Арестович LIVE"), завантажувати метадані, описи та субтитри (транскрипти), і конвертувати їх у Markdown-формат (з підтримкою YAML Frontmatter). Інструмент має вбудовану SQLite базу даних для відстеження вже оброблених відео, що дозволяє робити інкрементальні оновлення.

## Вимоги
- Python 3.10+
- yt-dlp
- webvtt-py
- pydantic
- pyyaml

## Встановлення

1. Клонуйте або завантажте цей репозиторій.
2. Створіть віртуальне середовище:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
3. Встановіть залежності:
   ```bash
   pip install -r requirements.txt
   ```

## Конфігурація

У файлі `config.yaml` можна налаштувати наступне:
- `channel_url`: URL YouTube-каналу або плейлиста.
- `match_filter`: Слово або фраза, яка обов'язково повинна бути в назві відео (наприклад, `Арестович LIVE`). Якщо залишити порожнім, шукатимуться всі відео.
- `output_dir`: Папка, куди зберігатимуться згенеровані `.md` файли.
- `db_path`: Шлях до файлу бази даних SQLite.
- `cookies_path`: Необов'язковий шлях до `cookies.txt` для авторизованих запитів до YouTube. За замовчуванням `null`, тоді скрипт автоматично прочитає cookies з Chrome.
- `proxy`: Необов'язковий HTTP/HTTPS proxy для обходу IP-блокування, якщо cookies не використовуються. За замовчуванням `null`.

Приклад:
```yaml
cookies_path: null  # Leave null to read cookies from Chrome automatically
proxy: null  # e.g. "http://user:pass@host:port"
```

### Автоматична авторизація YouTube

Якщо `cookies_path` порожній або файл не існує, скрипт автоматично прочитає cookies з вашого Chrome профілю через `yt-dlp`.

1. Переконайтеся, що ви вже увійшли в YouTube у Google Chrome.
2. Запустіть скрипт як зазвичай.
3. `yt-dlp` прочитає cookies з Chrome напряму для завантаження метаданих.
4. Для `youtube-transcript-api` скрипт створить тимчасовий Netscape `cookies.txt` з тих самих Chrome cookies.

На macOS `yt-dlp` використовує стандартний Chrome профіль, зокрема cookies database на кшталт `~/Library/Application Support/Google/Chrome/Default/Cookies`.

### Ручний cookies.txt

Якщо потрібно вручну передати cookies з браузера:

1. Встановіть Chrome extension [Get cookies.txt](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc).
2. Увійдіть у YouTube у Chrome.
3. Відкрийте `youtube.com`, натисніть іконку extension і експортуйте cookies у файл `cookies.txt`.
4. Вкажіть абсолютний шлях до файлу в `config.yaml`:
   ```yaml
   cookies_path: "/Users/me/cookies.txt"
   proxy: null
   ```

Файл `cookies.txt` містить дані сесії вашого акаунта, тому не додавайте його в git і не передавайте іншим людям.

## Використання

1. **Первинний запуск (Initial import)**
   Щоб обробити всі відео на каналі, що відповідають фільтру:
   ```bash
   python main.py --initial
   ```
   *Порада: для тестування можна обмежити кількість відео прапорцем `--limit 2`.*
   ```bash
   python main.py --initial --limit 2
   ```

2. **Інкрементальне оновлення (Update)**
   Для пошуку та обробки лише нових відео:
   ```bash
   python main.py --update
   ```

## Структура згенерованих файлів

Для кожного відео створюється `.md` файл, сумісний з Obsidian:
- YAML Frontmatter (`title`, `source`, `author`, `published`, `created`, `tags`).
- Embedded YouTube link.
- Опис відео.
- Список таймкодів (якщо знайдені в описі).
- Транскрипт (згрупований за таймкодами з опису, або одним блоком, якщо таймкоди відсутні).
