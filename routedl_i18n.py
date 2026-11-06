"""Переводы интерфейса RouteDL: исходные тексты в коде русские, английский подставляется переключателем.

Протокол между окном и консольным ядром остаётся русским и не меняется: переводится только то, что
показывается пользователю (подписи, статусы, строки лога).
"""
import re

LANG = "ru"


def set_lang(lang):
    global LANG
    LANG = "en" if lang == "en" else "ru"


def L(ru, en):
    """Строка под текущий язык (для динамических текстов, собираемых в коде)."""
    return en if LANG == "en" else ru


EN = {
    # подписи и подсказки
    "Вставьте ссылку на видео, аудио или галерею": "Paste a video, audio or gallery link",
    "Скачать как:": "Download as:",
    "Видео": "Video",
    "Аудио": "Audio",
    "Скачать весь плейлист": "Download the whole playlist",
    "Качество:": "Quality:",
    "Авто": "Auto",
    "Лучшее до 1080p": "Best up to 1080p",
    "Встроить обложку (только MP3)": "Embed cover art (MP3 only)",
    "Скачать": "Download",
    "Скачать. Несколько ссылок встанут в очередь и пойдут по одной": "Download. Several links are queued and run one by one",
    "Отмена": "Cancel",
    "Отменить текущую загрузку (очередь продолжится)": "Cancel the current download (the queue continues)",
    "Открыть папку": "Open folder",
    "Изменить папку загрузок…": "Change download folder…",
    "Отчёт": "Report",
    "Скопировать анонимный отчёт о последних запусках (для issue)": "Copy an anonymous report of recent runs (for an issue)",
    "Обновить движки": "Update engines",
    "Обновить yt-dlp и gallery-dl: сайты ломают их раз в 1-3 недели": "Update yt-dlp and gallery-dl: sites break them every 1-3 weeks",
    "Тест сети": "Network test",
    "Проверить, какие сайты открываются напрямую и где помогает обход. Результат копируется в буфер":
        "Check which sites open directly and where the bypass helps. The result is copied to the clipboard",
    "Резервные узлы (по умолчанию выключено)": "Backup nodes (off by default)",
    "Публичные анонимные узлы. Нужны, только если сайт отказывает по IP или стране.":
        "Public anonymous nodes. Needed only if a site refuses by IP or country.",
    "Повторить через резервные узлы…": "Retry via backup nodes…",
    "Продолжить восстановленную очередь": "Resume the restored queue",
    "Убрать выбранное": "Remove selected",
    "Ожидающее убирается из очереди, текущая загрузка отменяется":
        "A waiting item is removed from the queue, the current download is cancelled",
    "Очистить завершённые": "Clear finished",
    "Светлая тема": "Light theme",
    "Тёмная тема": "Dark theme",
    "Папка загрузок": "Downloads folder",
    "Резервные узлы": "Backup nodes",
    # бейдж маршрута
    "маршрут не выбран": "no route yet",
    "подбор маршрута": "choosing a route",
    "отменено": "cancelled",
    "Напрямую": "Direct",
    "Обход DPI": "DPI bypass",
    # статусы
    "Готов к работе": "Ready",
    "Вставьте ссылку, начинающуюся с http:// или https://": "Paste a link starting with http:// or https://",
    "Получаю сведения о ссылке…": "Getting link details…",
    "Получаю информацию о ссылке…": "Getting link information…",
    "Эта ссылка с такими же настройками уже в очереди (строка выделена)":
        "This link with the same settings is already in the queue (row highlighted)",
    "Загрузка…": "Downloading…",
    "Отмена…": "Cancelling…",
    "Конвертация в MP3: у длинных записей занимает несколько минут…": "Converting to MP3: long recordings take several minutes…",
    "Склейка видео и звука…": "Merging video and audio…",
    "Внимание: сайт отдаёт только 30-секундный фрагмент (трек платный или закрытый)":
        "Warning: the site only serves a 30-second preview (the track is paid or private)",
    "Не удалось получить сведения: будут настройки по умолчанию": "Could not get details: default settings will be used",
    "Отменено": "Cancelled",
    "Готово: файлы в папке загрузок": "Done: files are in the downloads folder",
    "Сайт отказал по IP или стране. Можно попробовать резервные узлы.": "The site refused by IP or country. You can try backup nodes.",
    "Не хватает места на диске: освободите место и повторите": "Not enough disk space: free some space and retry",
    "Нет интернета или не работает сеть: проверьте подключение": "No internet or the network is down: check your connection",
    "Эта ссылка не поддерживается": "This link is not supported",
    "Нет прогресса, загрузка прервана": "No progress, download aborted",
    "Отчёт скопирован в буфер обмена: вставьте его в issue": "Report copied to the clipboard: paste it into an issue",
    "Идёт загрузка или обновление: подождите": "A download or update is running: please wait",
    "Обновляю yt-dlp и gallery-dl…": "Updating yt-dlp and gallery-dl…",
    "Движки обновлены": "Engines updated",
    "Не удалось обновить движки (сеть или pip)": "Could not update engines (network or pip)",
    "Идёт загрузка или проверка: подождите": "A download or check is running: please wait",
    "Проверяю сеть: до минуты…": "Checking the network: up to a minute…",
    "Не удалось выполнить проверку сети": "Network check failed",
    "Результат скопирован в буфер обмена: вставьте его в issue": "Result copied to the clipboard: paste it into an issue",
    "Галерея изображений: считаю файлы…": "Image gallery: counting files…",
    "Галерея изображений (число файлов узнать не удалось)": "Image gallery (could not count the files)",
    "Сохранится как: MP3": "Will be saved as: MP3",
    "Сохранится как: FLAC (без потерь)": "Will be saved as: FLAC (lossless)",
    "Сохранится как: FLAC (без потерь, как в источнике)": "Will be saved as: FLAC (lossless, same as source)",
    "Сохранится как: WAV (без потерь, как в источнике)": "Will be saved as: WAV (lossless, same as source)",
    (
        "Резервные узлы это публичные анонимные серверы.\n\n"
        "Через них не передаются логины и cookies, но не вводите там пароли и личные данные.\n\n"
        "Повторить загрузку через них один раз?"
    ): (
        "Backup nodes are public anonymous servers.\n\n"
        "Logins and cookies are not sent through them, but do not enter passwords or personal data there.\n\n"
        "Retry the download through them once?"
    ),
    # причины сбоев
    "Сайт просит подтвердить, что вы не бот. Подождите несколько минут или смените сеть: вход в аккаунт RouteDL не поддерживает.":
        "The site asks you to confirm you are not a bot. Wait a few minutes or change networks: RouteDL does not support signing in.",
    "Ролик с ограничением по возрасту: без входа в аккаунт его не скачать, а RouteDL логины и cookies не использует.":
        "Age-restricted video: it cannot be downloaded without signing in, and RouteDL does not use logins or cookies.",
    "Приватное видео: доступно только владельцу или по приглашению.": "Private video: available only to the owner or by invitation.",
    "Видео только для участников канала.": "Members-only video.",
    "Видео удалено или недоступно.": "The video was removed or is unavailable.",
    "Видео недоступно в вашем регионе.": "The video is not available in your region.",
    "Сайт ограничил частоту запросов (429): подождите и повторите.": "The site rate-limited requests (429): wait and retry.",
    "Выбранное качество недоступно: выберите «Авто».": "The selected quality is unavailable: choose “Auto”.",
    "Трансляция или премьера ещё не началась.": "The stream or premiere has not started yet.",
    "Сайт, вероятно, сменил защиту. Нажмите «Обновить движки» и повторите.":
        "The site has probably changed its protection. Click “Update engines” and retry.",
    "Не найден ffmpeg: запустите install.bat.": "ffmpeg not found: run install.bat.",
    "Поток защищён DRM: скачать его нельзя.": "The stream is DRM-protected: it cannot be downloaded.",
}

_PAT = [
    # статусы окна
    (r"Файлов: (\d+) из (\d+)", r"Files: \1 of \2"),
    (r"Файлов: (\d+)", r"Files: \1"),
    (r"Трек (\d+) из (\d+) · (.*)", r"Track \1 of \2 · \3"),
    (r"Ошибка \(код (\d+)\), подробности в логе", r"Error (code \1), see the log for details"),
    (r"Галерея изображений: (\d+) файлов", r"Image gallery: \1 files"),
    (r"Это плейлист: (.+) элементов\. Отметьте, если нужно скачать все\.",
     r"This is a playlist: \1 items. Tick the box to download all."),
    (r"Восстановлена очередь: заданий (\d+)\. Продолжить или убрать лишнее\.",
     r"Queue restored: \1 items. Resume or remove the extras."),
    (r"Внимание: (.*)", r"Warning: \1"),
    (r"Не найден (.*)", r"Not found: \1"),
    (r"Папка загрузок: (.*)", r"Downloads folder: \1"),
    (r"Движки обновлены: (.*)", r"Engines updated: \1"),
    (r"Повторить через резервные узлы: (.*)", r"Retry via backup nodes: \1"),
    (r"Источник: (.*), без потерь", r"Source: \1, lossless"),
    (r"Источник: (.*), сжатый \(с потерями\)", r"Source: \1, lossy"),
    (r"Не удалось запустить (.*)", r"Failed to start \1"),
    # результат «Тест сети»
    (r"(\S+\s+)открывается напрямую", r"\1opens directly"),
    (r"(\S+\s+)помогает обход: (.*)", r"\1bypass helps: \2"),
    (r"(\S+\s+)закрыт \(нет ciadpi\.exe\)", r"\1blocked (ciadpi.exe missing)"),
    (r"(\S+\s+)закрыт, ни одна стратегия не помогла", r"\1blocked, no strategy helped"),
    # строки лога ядра
    (r"движок: (\w+) \(yt-dlp знает: (\w+), gallery-dl знает: (\w+)\)",
     r"engine: \1 (yt-dlp knows: \2, gallery-dl knows: \3)"),
    (r"ни один движок не знает эту ссылку", "no engine knows this link"),
    (r"--audio работает только с yt-dlp, игнорирую", "--audio works only with yt-dlp, ignoring"),
    (r"нет подключения к интернету или не работает сеть \(это не проблема программы\)",
     "no internet connection or the network is down (not a program problem)"),
    (r"нет подключения к интернету или не работает сеть", "no internet connection or the network is down"),
    (r"запомненный маршрут старше 3 ч, перепроверяю с прямого", "remembered route is older than 3 h, re-checking from direct"),
    (r"запомненный маршрут не сработал, начинаю с прямого", "remembered route failed, starting from direct"),
    (r"готово, код (\d+)", r"done, code \1"),
    (r"мало места на диске: свободно (.+) ГБ, нужно не меньше (.+) ГБ", r"low disk space: \1 GB free, at least \2 GB needed"),
    (r"обновляю список узлов \(через DPI-обход\)\.\.\.", "updating the node list (through DPI bypass)..."),
    (r"обновляю список узлов\.\.\.", "updating the node list..."),
    (r"список не скачался с (.*)", r"node list download failed from \1"),
    (r"беру локальную копию списка", "using the local copy of the list"),
    (r"живых узлов найдено: (\d+)", r"live nodes found: \1"),
    (r"иностранных узлов для этого сайта не нашлось, беру любой", "no foreign nodes for this site, taking any"),
    (r"подбираю стратегию DPI-обхода \(параллельно, (\d+) шт\.\)\.\.\.", r"testing DPI bypass strategies (in parallel, \1)..."),
    (r"стратегия из кэша: (.*)", r"strategy from cache: \1"),
    (r"стратегия: (.*) \(подошло (\d+) из (\d+)\)", r"strategy: \1 (\2 of \3 worked)"),
    (r"напрямую: нет соединения с сайтом", "direct: cannot reach the site"),
    (r"ciadpi\.exe не найден, пропускаю DPI-обход", "ciadpi.exe not found, skipping DPI bypass"),
    (r"ни одна стратегия не сработала", "no strategy worked"),
    (r"нужен ciadpi\.exe для цепочки, пропускаю узлы", "ciadpi.exe is needed for the chain, skipping nodes"),
    (r"узлы через DPI-обход", "nodes through DPI bypass"),
    (r"DPI-обход не поднялся, узлы недоступны", "DPI bypass did not start, nodes unavailable"),
    (r"ни один узел не открывает этот сайт", "no node opens this site"),
    (r"выбран узел \(порт (\d+), выход: (.*)\)", r"node selected (port \1, exit: \2)"),
    (r"маршрут: напрямую", "route: direct"),
    (r"маршрут: локальный DPI-обход \(ByeDPI\)", "route: local DPI bypass (ByeDPI)"),
    (r"маршрут: через узлы", "route: backup nodes"),
    (r"закончилось место на диске: освободите место и повторите \(скачанное сохранится\)",
     "disk full: free some space and retry (what was downloaded is kept)"),
    (r"сайт отказал по IP или стране, пробую узлы", "the site refused by IP or country, trying nodes"),
    (r"сайт отказал по IP или стране; резервные узлы выключены \(включаются флагом --nodes\)",
     "the site refused by IP or country; backup nodes are off (enable with --nodes)"),
    (r"ролик недоступен на самом сайте: смена маршрута не поможет",
     "the video is unavailable on the site itself: changing the route will not help"),
    (r"поток HLS несовместим с докачкой кусками: повторяю без неё", "HLS stream is incompatible with chunked resume: retrying without it"),
    (r"докачка пропущенных файлов \(проход (\d+)\)", r"fetching missed files (pass \1)"),
    (r"последний маршрут не справился: повторяю осторожно \(1 поток, таймаут 30 с\)",
     "the last route failed: retrying gently (1 thread, 30 s timeout)"),
    (r"\[RouteDL\] предупреждение: сайт отдаёт только 30-секундный фрагмент этого трека \(полная запись платная или закрытая\)",
     "[RouteDL] warning: the site only serves a 30-second preview of this track (the full recording is paid or private)"),
    (r"ERROR: stalled, timed out: нет прогресса (\d+) с, загрузка прервана",
     r"ERROR: stalled, timed out: no progress for \1 s, download aborted"),
]
PAT = [(re.compile(p, re.S), r) for p, r in _PAT]
FRAG = [("нет в bin: ", "missing in bin: "), ("не найден Deno (нужен для YouTube)", "Deno not found (needed for YouTube)"),
        (" кбит/с", " kbps")]
_TITLE = [(re.compile(p), r) for p, r in [
    (r"^Галерея \((\d+) файлов\): ", r"Gallery (\1 files): "),
    (r"^Галерея: ", "Gallery: "),
    (r" \(плейлист, аудио\)", " (playlist, audio)"),
    (r" \(плейлист, видео\)", " (playlist, video)"),
    (r" \(через узлы\)$", " (via nodes)"),
    (r" \(аудио\)$", " (audio)"),
]]
_PREFIX = re.compile(r"^(\[RouteDL \+\d+)с\] (.*)$", re.S)


def tr(text):
    """Перевод строки целиком (точное совпадение или шаблон). Незнакомый текст, например название видео, не трогается."""
    if LANG != "en" or not text:
        return text
    core = text.strip()
    if not core:
        return text
    pre, post = text[:len(text) - len(text.lstrip())], text[len(text.rstrip()):]
    if core in EN:
        return pre + EN[core] + post
    for rx, rep in PAT:
        m = rx.fullmatch(core)
        if m:
            out = m.expand(rep)
            for a, b in FRAG:
                out = out.replace(a, b)
            return pre + out + post
    return text


def tr_line(line):
    """Строка лога: префикс «[RouteDL +5с]» превращается в «+5s», остальное переводится целиком."""
    if LANG != "en":
        return line
    m = _PREFIX.match(line)
    if m:
        return f"{m.group(1)}s] " + tr(m.group(2))
    return tr(line)


def tr_title(title):
    """Название задания в очереди: переводятся только добавленные программой пометки, название видео остаётся."""
    if LANG != "en":
        return title
    for rx, rep in _TITLE:
        title = rx.sub(rep, title)
    return title
