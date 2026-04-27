# YouTube to Markdown Exporter

Цей інструмент автоматично знаходить відео на YouTube каналі за фільтрами, завантажує метадані, витягує MP3-аудіо, транскрибує його через Groq-hosted Whisper STT з chunking/overlap, зшиває транскрипт і конвертує результат у Markdown-нотатки для Obsidian. Інструмент має SQLite базу для сумісного відстеження вже оброблених відео та JSON state-файл для resume на рівні audio/chunks/transcription.

## Вимоги
- Python 3.10+
- yt-dlp
- ffmpeg / ffprobe
- webvtt-py
- pydantic
- pyyaml
- groq

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
4. Вкажіть Groq API key:
   ```bash
   export GROQ_API_KEY="your_groq_api_key"
   ```

## Конфігурація

У файлі `config.yaml` можна налаштувати наступне:
- `channel_url`: URL YouTube-каналу або плейлиста.
- `match_filter`: Слово або фраза, яка обов'язково повинна бути в назві відео (наприклад, `Арестович LIVE`). Якщо залишити порожнім, шукатимуться всі відео.
- `output_dir`: Папка, куди зберігатимуться згенеровані `.md` файли.
- `db_path`: Шлях до файлу бази даних SQLite.
- `state_path`: JSON state-файл для resume після переривань.
- `cookies_path`: Необов'язковий шлях до `cookies.txt` для авторизованих запитів до YouTube. За замовчуванням `null`, тоді скрипт автоматично прочитає cookies з Chrome.
- `proxy`: Необов'язковий HTTP/HTTPS proxy для обходу IP-блокування, якщо cookies не використовуються. За замовчуванням `null`.
- `groq_api_key`: Можна залишити `null`; тоді ключ читається з `GROQ_API_KEY`.
- `groq_model`: Whisper model на Groq, за замовчуванням `whisper-large-v3-turbo`.
- `transcription_language`: Мова транскрипції (`ru`, `uk`, `en`) або `null` для auto-detect.
- `chunk_duration_seconds`: Тривалість аудіо-chunk, за замовчуванням `600`.
- `chunk_overlap_seconds`: Overlap між chunk, за замовчуванням `5`.
- `max_retries`: Кількість повторів для Groq API.
- `retry_backoff_seconds`: Базова затримка retry/backoff.
- `combined_markdown_filename`: Назва об'єднаного Markdown-файлу.

Приклад:
```yaml
cookies_path: null  # Leave null to read cookies from Chrome automatically
proxy: null  # e.g. "http://user:pass@host:port"
groq_api_key: null
groq_model: "whisper-large-v3-turbo"
transcription_language: null
chunk_duration_seconds: 600
chunk_overlap_seconds: 5
max_retries: 5
retry_backoff_seconds: 2.0
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

3. **Resume після переривання**
   Повторно запустіть ту саму команду. Pipeline пропустить вже витягнуте аудіо, використає наявні chunks або готовий stitched transcript, і продовжить з останнього записаного chunk.

4. **Скидання state**
   SQLite база та `state.json` зберігаються окремо. Щоб явно скинути JSON resume-state:
   ```bash
   python main.py --reset-state
   ```

## Структура згенерованих файлів

Для кожного відео створюється `.md` файл, сумісний з Obsidian:
- YAML Frontmatter (`title`, `source`, `author`, `published`, `created`, `tags`).
- Embedded YouTube link.
- Опис відео.
- Related concepts як Obsidian wiki-links на основі тегів відео.
- Список таймкодів (якщо знайдені в описі).
- Транскрипт Groq Whisper (згрупований за таймкодами з опису, або одним блоком, якщо таймкоди відсутні).
- `combined_notes.md` з усіма generated notes в алфавітному порядку.

MP3-файли зберігаються в `output_dir/_audio`. Тимчасові chunk-файли створюються в `output_dir/_chunks` і видаляються після успішної транскрипції. Stitched transcripts зберігаються в `output_dir/_transcripts`, щоб повторні запуски могли пропустити Groq transcription і продовжити Markdown generation.
