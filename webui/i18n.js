/* Interface translation.
 *
 * The markup and app.js are written in English. When the launcher language is
 * Russian, this module swaps every known English text node and attribute for
 * its Russian counterpart and keeps translating whatever the app renders
 * afterwards (it observes the DOM). Switching back restores the stored English
 * originals, so the dictionary never has to be applied twice.
 */
(function () {
  "use strict";

  const RU = {
    /* Shell and navigation */
    "launcher": "лаунчер",
    "Profiles": "Сборки",
    "New": "Новая",
    "Skins": "Скины",
    "Bypass": "Обход",
    "Network bypass (zapret) for blocked Minecraft servers and mod sites. Changes are saved automatically.": "Обход блокировок (zapret) для серверов Minecraft и сайтов модов. Изменения сохраняются автоматически.",
    "Settings": "Настройки",
    "PROFILES": "СБОРКИ",
    "empty": "пусто",
    "No profiles yet": "Пока нет сборок",
    "A profile is an isolated game folder — its own worlds, mods and settings. Shared files stay in": "Сборка — это отдельная папка игры: свои миры, моды и настройки. Общие файлы остаются в",
    "Create the first profile": "Создать первую сборку",
    "Profile": "Сборка",
    "vanilla": "ванильная",
    "Play": "Играть",
    "Stop": "Остановить",
    "Restart": "Перезапустить",
    "Mods": "Моды",
    "Resource packs": "Ресурспаки",
    "Shader packs": "Шейдеры",
    "Worlds": "Миры",
    "Screenshots": "Скриншоты",
    "Logs": "Логи",
    "Crash": "Сбой",
    "Error": "Ошибка",
    "Game crash": "Игра вылетела",
    "Launcher error": "Ошибка лаунчера",
    "Dismiss": "Закрыть",
    "Dismiss notification": "Закрыть уведомление",
    "Profile settings": "Настройки сборки",
    "Installed mods": "Установленные моды",
    "Update all": "Обновить все",
    "Any version": "Любая версия",
    "Browse mods": "Обзор модов",
    "Open folder": "Открыть папку",
    "Browse packs": "Обзор ресурспаков",
    "Browse shaders": "Обзор шейдеров",
    "Backup worlds": "Резервная копия миров",
    "Folder": "Папка",
    "Clear view": "Очистить",
    "Account": "Аккаунт",
    "Launcher default": "Как в настройках",
    "Memory": "Память",
    "Used when this profile starts the game": "Используется при запуске этой сборки",
    "Java": "Java",
    "Downloaded automatically": "Загружается автоматически",
    "Automatic": "Автоматически",
    "Version": "Версия",
    "CHANGE VERSION": "СМЕНИТЬ ВЕРСИЮ",
    "Minecraft": "Minecraft",
    "Mod loader": "Загрузчик модов",
    "No loader (vanilla)": "Без загрузчика (ванильная)",
    "Loader version": "Версия загрузчика",
    "Apply changes": "Применить изменения",
    "Icon": "Иконка",
    "Set icon": "Выбрать иконку",
    "Banner": "Фон сборки",
    "Set banner": "Выбрать фон",
    "PNG, JPG, WEBP, GIF, MP4 or WebM shown at the top of this build": "PNG, JPG, WEBP, GIF, MP4 или WebM в верхней части сборки",
    "Build banner updated.": "Фон сборки обновлён.",
    "Build banner removed.": "Фон сборки убран.",
    "Choose a PNG, JPG, WEBP, GIF, MP4 or WebM file.": "Выберите файл PNG, JPG, WEBP, GIF, MP4 или WebM.",
    "That image is larger than 20 MB.": "Изображение больше 20 МБ.",
    "That video is larger than 50 MB.": "Видео больше 50 МБ.",
    "That file no longer exists.": "Этот файл больше не существует.",
    "Remove": "Удалить",
    "Game folder": "Папка игры",
    "Open": "Открыть",
    "Edit profile": "Изменить сборку",
    "All settings": "Все настройки",
    "New profile": "Новая сборка",
    "Pick any Minecraft version — missing files are downloaded from Mojang.": "Выберите любую версию Minecraft — недостающие файлы загрузятся с Mojang.",
    "PROFILE NAME": "НАЗВАНИЕ СБОРКИ",
    "MINECRAFT VERSION": "ВЕРСИЯ MINECRAFT",
    "Refresh": "Обновить",
    "Show all versions": "Показать все версии",
    "Releases only": "Только релизы",
    "Releases": "Релизы",
    "Snapshots": "Снимки",
    "Old betas": "Старые беты",
    "Old alphas": "Старые альфы",
    "MOD LOADER": "ЗАГРУЗЧИК МОДОВ",
    "None": "Нет",
    "LOG": "ЛОГ",
    "Clear": "Очистить",
    "Pick a version to begin.": "Выберите версию, чтобы начать.",
    "Create profile": "Создать сборку",
    "Cancel": "Отмена",
    "Save changes": "Сохранить изменения",
    "Search Modrinth by name.": "Поиск по Modrinth по названию.",
    "Paste a CurseForge link, ID or exact slug": "Вставьте ссылку, ID или точный слаг CurseForge",
    "Search CurseForge mods by name": "Поиск модов CurseForge по названию",
    "Search CurseForge resource packs by name": "Поиск ресурспаков CurseForge по названию",
    "Search CurseForge shaders by name": "Поиск шейдеров CurseForge по названию",
    "Search CurseForge modpacks by name": "Поиск модпаков CurseForge по названию",
    "Install selected (0)": "Установить выбранные (0)",
    "Open mods folder": "Открыть папку модов",
    "Open resource packs": "Открыть ресурспаки",
    "Open shaders": "Открыть шейдеры",
    "Shaders": "Шейдеры",
    "Modpacks": "Модпаки",
    "Any": "Любой",
    "Search": "Найти",
    "Select a mod": "Выберите мод",
    "Select a resource pack": "Выберите ресурспак",
    "Select a shader pack": "Выберите шейдерпак",
    "Select a modpack": "Выберите модпак",
    "Install": "Установить",
    "Uninstall": "Удалить",
    "Update": "Обновить",
    "Add profile": "Добавить сборку",
    "Select a profile to install a loader.": "Выберите сборку, чтобы установить загрузчик.",
    "Refresh builds": "Обновить сборки",
    "BUILDS": "СБОРКИ",
    /* Home — the main menu screen */
    "Home": "Главная",
    "MAIN MENU": "ГЛАВНОЕ МЕНЮ",
    "0 min": "0 мин",
    "< 1 min": "меньше минуты",
    "RECENT WORLDS": "НЕДАВНИЕ МИРЫ",
    "New build": "Новая сборка",
    "No recent worlds yet.": "Пока нет недавних миров.",
    "Create a profile to get started.": "Создайте сборку, чтобы начать.",
    "Play this build": "Играть в эту сборку",
    "Stop the game": "Остановить игру",
    "This profile is already running.": "Эта сборка уже запущена.",
    "Pick a loader build.": "Выберите сборку загрузчика.",
    "Install loader": "Установить загрузчик",
    "Search mods by name": "Поиск модов по названию",
    "Search resource packs by name": "Поиск ресурспаков по названию",
    "Search shaders by name": "Поиск шейдеров по названию",
    "Search modpacks by name": "Поиск модпаков по названию",
    "Search Modrinth to find mods for this profile.": "Найдите моды для этой сборки в Modrinth.",
    "Search Modrinth to find resource packs for this profile.": "Найдите ресурспаки для этой сборки в Modrinth.",
    "Search Modrinth to find shaders for this profile.": "Найдите шейдеры для этой сборки в Modrinth.",
    "Search Modrinth to find a modpack — it installs as a new profile.": "Найдите модпак в Modrinth — он установится как новая сборка.",
    "Modrinth · modpacks · installs as a new profile": "Modrinth · модпаки · устанавливаются как новая сборка",
    "Search CurseForge to find mods for this profile.": "Найдите моды для этой сборки в CurseForge.",
    "Search CurseForge to find resource packs for this profile.": "Найдите ресурспаки для этой сборки в CurseForge.",
    "Search CurseForge to find shaders for this profile.": "Найдите шейдеры для этой сборки в CurseForge.",
    "Search CurseForge to find a modpack — it installs as a new profile.": "Найдите модпак в CurseForge — он установится как новая сборка.",
    "Paste a CurseForge project link or exact slug, or add an API key in Settings → Network.": "Вставьте ссылку на проект CurseForge или точный слаг либо добавьте API-ключ в «Настройки → Сеть».",
    "No builds loaded.": "Сборки не загружены.",
    "No loader — vanilla profile.": "Без загрузчика — ванильная сборка.",
    "Pick a loader above.": "Выберите загрузчик выше.",
    "Pick a loader build, or set the loader to None.": "Выберите сборку загрузчика или укажите «Нет».",
    "Choose a mod loader first.": "Сначала выберите загрузчик модов.",
    "Vanilla profile — no mod loader will be installed.": "Ванильная сборка — загрузчик модов не устанавливается.",
    "Nothing matches — clear the search or enable more types.": "Ничего не найдено — очистите поиск или включите другие типы.",
    "Nothing matches — clear the search or show all versions.": "Ничего не найдено — очистите поиск или покажите все версии.",
    "No versions match the search.": "По запросу версий не найдено.",
    "No versions found — refresh the list.": "Версии не найдены — обновите список.",
    "No versions match the selected types.": "Нет версий выбранных типов.",
    "Refreshing the Mojang version list…": "Обновляем список версий Mojang…",
    "Loading the Minecraft version list from Mojang…": "Загружаем список версий Minecraft с Mojang…",
    "Scroll for more": "Прокрутите, чтобы увидеть больше",
    "Add to the batch": "Добавить в набор",
    "Loading…": "Загрузка…",
    "Reading the profile folder…": "Читаем папку сборки…",
    "No mods yet. Use Browse mods to install one.": "Модов пока нет. Нажмите «Обзор модов», чтобы установить.",
    "No resource packs installed.": "Ресурспаки не установлены.",
    "No shader packs installed.": "Шейдеры не установлены.",
    "No worlds yet. Start the game to create one.": "Миров пока нет. Запустите игру, чтобы создать мир.",
    "No screenshots yet. Press F2 in game to take one.": "Скриншотов пока нет. Нажмите F2 в игре.",
    "Open the world folder": "Открыть папку мира",
    "Copy": "Копировать",
    "Open file": "Открыть файл",
    "Close": "Закрыть",
    "Minimize": "Свернуть",
    "Maximize": "Развернуть",
    "Restore": "Восстановить",
    "Copy screenshot": "Копировать скриншот",
    "Screenshot copied to the clipboard.": "Скриншот скопирован в буфер обмена.",
    "Could not copy the screenshot.": "Не удалось скопировать скриншот.",
    "That screenshot is not valid.": "Некорректный скриншот.",
    "That screenshot no longer exists.": "Этот скриншот больше не существует.",
    "untracked": "без учёта",
    "This profile is already running.": "Эта сборка уже запущена.",
    "Starting…": "Запуск…",
    "Confirm delete": "Подтвердите удаление",
    "Delete": "Удалить",
    "Change the name, Minecraft version or mod loader. Worlds, mods and configs stay in place.": "Измените название, версию Minecraft или загрузчик модов. Миры, моды и конфиги останутся на месте.",

    /* Accounts */
    "Account and Minecraft launch options. Changes are saved automatically.": "Аккаунт и параметры запуска Minecraft. Изменения сохраняются автоматически.",
    "Shared folder": "Общая папка",
    "ACCOUNT": "АККАУНТ",
    "offline": "оффлайн",
    "Drag an account with the mouse to change its order.": "Перетаскивайте аккаунт мышью, чтобы изменить порядок.",
    "ADD ACCOUNT": "ДОБАВИТЬ АККАУНТ",
    "Microsoft": "Microsoft",
    "Ely.by": "Ely.by",
    "Offline": "Оффлайн",
    "Not signed in": "Вход не выполнен",
    "Sign in to add a Microsoft account. You can add more than one and switch between them at any time.": "Войдите, чтобы добавить аккаунт Microsoft. Аккаунтов может быть несколько — переключайтесь между ними в любое время.",
    "Sign in": "Войти",
    "SIGN-IN CODE": "КОД ДЛЯ ВХОДА",
    "Enter this code at": "Введите этот код на",
    ". The browser should open by itself; you can also open the page on any device.": ". Браузер должен открыться сам; страницу можно открыть и на другом устройстве.",
    "Advanced: Azure Client ID": "Дополнительно: Azure Client ID",
    "A built-in Client ID is already configured — leave the field empty to use it. Paste your own Azure application ID only if you want a different app registration.": "Встроенный Client ID уже настроен — оставьте поле пустым, чтобы использовать его. Вставляйте свой Azure Application ID, только если нужна другая регистрация приложения.",
    "AZURE CLIENT ID": "AZURE CLIENT ID",
    "Save": "Сохранить",
    "How to get your own Client ID (free, ~5 minutes)": "Как получить свой Client ID (бесплатно, ~5 минут)",
    "and sign in.": "и войдите.",
    "Go to": "Перейдите в",
    "Name it anything, pick": "Назовите как угодно, выберите",
    "Personal Microsoft accounts only": "Только личные аккаунты Microsoft",
    ", then press": ", затем нажмите",
    "Register": "Register",
    "Copy the": "Скопируйте",
    "from the overview page.": "со страницы обзора.",
    ", set": ", установите",
    "to": "в",
    "and save.": "и сохраните.",
    "Paste the ID above, press Save, then Sign in.": "Вставьте ID выше, нажмите Save, затем Sign in.",
    "Sign in with browser": "Войти через браузер",
    "A browser page opens on ely.by — sign in there and the launcher picks your account up automatically. No password to type here.": "Откроется страница ely.by — войдите там, и лаунчер подхватит аккаунт автоматически. Пароль здесь вводить не нужно.",
    "Waiting for the browser…": "Ждём браузер…",
    "Finish signing in on the ely.by page that just opened.": "Завершите вход на только что открытой странице ely.by.",
    "Sign in with password instead": "Войти по паролю",
    "ELY.BY EMAIL OR USERNAME": "ELY.BY: ПОЧТА ИЛИ НИК",
    "PASSWORD": "ПАРОЛЬ",
    "TWO-FACTOR CODE": "КОД ДВУХФАКТОРКИ",
    "Sign in with Ely.by": "Войти через Ely.by",
    "The password goes only to ely.by and is never stored. First launch downloads authlib-injector, which signs the game in and loads Ely.by skins.": "Пароль отправляется только на ely.by и не сохраняется. При первом запуске скачается authlib-injector — он выполняет вход в игру и загружает скины Ely.by.",
    "Advanced: browser sign-in (OAuth) setup": "Дополнительно: настройка входа через браузер (OAuth)",
    "Browser sign-in only needs an Ely.by Client ID for a “Desktop application” (PKCE, no secret). A “Website” app also works — then paste its Client Secret too. Enter them here once; everyone using this copy of the launcher can then sign in with the button above.": "Для входа через браузер нужен Client ID приложения Ely.by типа “Desktop application” (PKCE, без секрета). Подойдёт и “Website” — тогда добавьте Client Secret. Введите их один раз: после этого кнопка входа будет работать для всех, кто пользуется этой копией лаунчера.",
    "OAUTH CLIENT ID": "OAUTH CLIENT ID",
    "OAUTH CLIENT SECRET (OPTIONAL)": "OAUTH CLIENT SECRET (НЕОБЯЗАТЕЛЬНО)",
    "REDIRECT URI": "REDIRECT URI",
    "How to get a Client ID (and a Secret)": "Как получить Client ID (и Secret)",
    "Open your applications page and create a new application.": "Откройте страницу приложений и создайте новое приложение.",
    "is the simplest choice: it uses PKCE, so only a Client ID is needed.": "— простейший вариант: используется PKCE, поэтому нужен только Client ID.",
    "also works but then the Client Secret is required.": "тоже подойдёт, но тогда потребуется Client Secret.",
    "Add the exact": "Добавьте точный",
    "shown above (by default": "указанный выше (по умолчанию",
    ") to that application.": ") в это приложение.",
    "Copy the application's": "Скопируйте",
    "— and its": "— и",
    "if it has one — into the fields above and press Save.": "если он есть — в поля выше и нажмите Save.",
    "Press": "Нажмите",
    "Add": "Add",
    "Offline accounts skip signing in. The game uses the name you type here; skins come from the profile files.": "Оффлайн-аккаунты не требуют входа. Игра использует введённое имя; скины берутся из файлов сборки.",
    "No accounts yet — add one below.": "Аккаунтов пока нет — добавьте ниже.",
    "Microsoft account": "Аккаунт Microsoft",
    "Ely.by account": "Аккаунт Ely.by",
    "Offline account": "Оффлайн-аккаунт",
    "Sign in with your Nexi account": "Войдите в аккаунт Nexi",
    "Use the Nexi ID, e-mail or @username of your account on the Nexi site.": "Введите Nexi ID, email или @имя пользователя вашего аккаунта на сайте Nexi.",
    "NEXI ID, E-MAIL OR @USERNAME": "NEXI ID, EMAIL ИЛИ @ИМЯ ПОЛЬЗОВАТЕЛЯ",
    "A 6-digit code arrives by e-mail and confirms the sign-in. The password goes only to the Nexi site and is never stored.": "На почту придёт 6-значный код для подтверждения. Пароль отправляется только на сайт Nexi и не сохраняется.",
    "We sent a code to your e-mail.": "Мы отправили код на вашу почту.",
    "CODE FROM THE E-MAIL": "КОД ИЗ ПИСЬМА",
    "Confirm": "Подтвердить",
    "Nexi account": "Аккаунт Nexi",
    "Minecraft account": "Аккаунт Minecraft",
    "Minecraft nickname": "Ник в Minecraft",
    "Link": "Привязать",
    "Unlink": "Отвязать",
    "NEXI SITE": "САЙТ NEXI",
    "signed in": "вход выполнен",
    "not signed in": "вход не выполнен",
    "Change linked account": "Сменить аккаунт",
    "The Minecraft account linked to your Nexi profile on the site. Microsoft and Ely.by nicknames are verified by the site before they are saved.": "Minecraft-аккаунт, привязанный к вашему профилю Nexi на сайте. Ники Microsoft и Ely.by проверяются сайтом перед сохранением.",
    "Refresh profile": "Обновить профиль",
    "Sign out": "Выйти",
    "Advanced: Nexi site address": "Дополнительно: адрес сайта Nexi",
    "SITE ADDRESS": "АДРЕС САЙТА",
    "Used for Nexi sign-in and profile sync. Change it if the site runs on another address or domain.": "Используется для входа через Nexi и синхронизации профиля. Измените, если сайт работает по другому адресу или домену.",
    "Enter your Nexi ID and password.": "Введите Nexi ID и пароль.",
    "Sending the sign-in code…": "Отправляем код для входа…",
    "Enter the code from the e-mail.": "Введите код из письма.",
    "Could not confirm the code.": "Не удалось подтвердить код.",
    "Nexi sign-in cancelled.": "Вход через Nexi отменён.",
    "Could not sign out of Nexi.": "Не удалось выйти из аккаунта Nexi.",
    "Signed out of Nexi.": "Вы вышли из аккаунта Nexi.",
    "Could not refresh the Nexi profile.": "Не удалось обновить профиль Nexi.",
    "Nexi profile refreshed.": "Профиль Nexi обновлён.",
    "Profile on the Nexi site": "Профиль на сайте Nexi",
    "The Nexi site is not running.": "Сайт Nexi не запущен.",
    "Open your profile on the Nexi site": "Открыть профиль на сайте Nexi",
    "Sign in with Nexi to open your site profile": "Войдите через Nexi, чтобы открыть профиль на сайте",
    "Could not open the site profile.": "Не удалось открыть профиль на сайте.",
    "Sign in with your Nexi account first.": "Сначала войдите в аккаунт Nexi.",
    "Could not read the Nexi profile.": "Не удалось прочитать профиль Nexi.",
    "Could not find this profile on the Nexi site.": "Не удалось найти этот профиль на сайте Nexi.",
    "Type the Minecraft nickname.": "Введите ник в Minecraft.",
    "Could not link the Minecraft account.": "Не удалось привязать Minecraft-аккаунт.",
    "Minecraft account linked.": "Minecraft-аккаунт привязан.",
    "Could not unlink the Minecraft account.": "Не удалось отвязать Minecraft-аккаунт.",
    "Minecraft link removed.": "Привязка Minecraft удалена.",
    "Could not save the Nexi site address.": "Не удалось сохранить адрес сайта Nexi.",
    "Nexi site address saved.": "Адрес сайта Nexi сохранён.",
    "Active": "Активный",
    "Use": "Использовать",
    "Built-in Client ID is used": "Используется встроенный Client ID",
    "Application (client) ID": "Application (client) ID",
    "Client ID from account.ely.by": "Client ID из account.ely.by",
    "Leave blank to use PKCE (no secret)": "Оставьте пустым для PKCE (без секрета)",
    "Saved — leave blank to keep": "Сохранено — оставьте пустым, чтобы не менять",
    "A browser page opens on ely.by — sign in there and the launcher adds that account automatically. No password to type here.": "Откроется страница ely.by — войдите там, и лаунчер автоматически добавит аккаунт. Пароль здесь вводить не нужно.",
    "Browser sign-in is not configured yet. Open “Advanced: browser sign-in (OAuth) setup” below and add an Ely.by Client ID — a “Desktop application” app (PKCE) needs no secret — or use the password form.": "Вход через браузер ещё не настроен. Откройте ниже «Дополнительно: настройка входа через браузер (OAuth)» и добавьте Client ID Ely.by — приложению “Desktop application” (PKCE) секрет не нужен — или войдите по паролю.",
    "Browser sign-in is ready — a built-in Ely.by Client ID is used (PKCE, no secret). You can override it below.": "Вход через браузер готов — используется встроенный Client ID Ely.by (PKCE, без секрета). Его можно переопределить ниже.",
    "Browser sign-in is configured. You can change the credentials below at any time.": "Вход через браузер настроен. Учётные данные можно изменить ниже в любое время.",

    /* Settings tabs and per-profile game defaults */
    "Settings sections": "Разделы настроек",
    "Accounts": "Аккаунты",
    "Game": "Игра",
    "Appearance": "Оформление",
    "Network": "Сеть",
    "Launcher": "Лаунчер",
    "SKIN": "СКИН",
    "GAME DEFAULTS": "НАСТРОЙКИ ИГРЫ",
    "Written to the selected profile's options.txt every time it starts. Pick a profile in the rail on the left.": "Записываются в options.txt выбранной сборки при каждом запуске. Выберите сборку в списке слева.",
    "GUI SCALE": "МАСШТАБ ИНТЕРФЕЙСА",
    "PARTICLES": "ЧАСТИЦЫ",
    "FPS LIMIT": "ЛИМИТ FPS",
    "FOV": "FOV",
    "RENDER DISTANCE": "ДАЛЬНОСТЬ ПРОРИСОВКИ",
    "BRIGHTNESS": "ЯРКОСТЬ",
    "Auto": "Авто",
    "All": "Все",
    "Decreased": "Меньше",
    "Minimal": "Минимум",
    "Unlimited": "Без ограничения",
    "Field of view": "Угол обзора",
    "Render distance": "Дальность прорисовки",
    "Brightness": "Яркость",
    "Values changed inside the game are replaced by these on the next launch.": "Значения, изменённые в игре, будут заменены этими при следующем запуске.",
    "Apply now": "Применить сейчас",
    "No profile selected": "Сборка не выбрана",
    "Select a profile first.": "Сначала выберите сборку.",
    "Game defaults saved.": "Настройки игры сохранены.",
    "Game defaults written to options.txt.": "Настройки игры записаны в options.txt.",
    "Could not save game defaults.": "Не удалось сохранить настройки игры.",
    "Could not write options.txt.": "Не удалось записать options.txt.",

    /* Settings */
    "Memory for new profiles": "Память для новых сборок",
    "Every new profile starts with this much RAM.": "Каждая новая сборка стартует с этим объёмом ОЗУ.",
    "Memory for this profile": "Память для этой сборки",
    "Select a profile to change its memory.": "Выберите сборку, чтобы изменить её память.",
    "JAVA EXECUTABLE": "JAVA: ИСПОЛНЯЕМЫЙ ФАЙЛ",
    "Browse…": "Обзор…",
    "Leave empty — the launcher downloads the Java runtime each version needs.": "Оставьте пустым — лаунчер скачает нужную версию Java.",
    "Use automatic": "Автоматически",
    "APPEARANCE": "ОФОРМЛЕНИЕ",
    "Mint": "Мята",
    "#6EE7B7 · default": "#6EE7B7 · по умолчанию",
    "Soft orange": "Мягкий оранжевый",
    "Indigo": "Индиго",
    "Accent colour of the whole launcher — buttons, highlights, glows and the skin viewer ambience.": "Акцентный цвет всего лаунчера — кнопки, выделения, свечение и фон просмотра скина.",
    "Colour mode": "Цветовая тема",
    "Dark is the default; light switches to white surfaces.": "Тёмная используется по умолчанию; светлая делает фон белым.",
    "Dark": "Тёмная",
    "Light": "Светлая",
    "Language": "Язык",
    "Interface language. Changes apply right away.": "Язык интерфейса. Изменения применяются сразу.",
    "Home background": "Фон главного меню",
    "A GIF, MP4 or WebM clip behind the main menu. Leave it empty to keep the animated panorama.": "GIF, MP4 или WebM на фоне главного меню. Оставьте пустым, чтобы осталась анимированная панорама.",
    "Choose a background…": "Выбрать фон…",
    "Use panorama": "Панорама",
    "Panorama": "Панорама",
    "Top bar companion": "Компаньон на верхней панели",
    "Who keeps you company in the corner of the top bar. Pick one up to drag it around.": "Кто сидит в углу верхней панели. Его можно взять и перетащить.",
    "Could not save the companion.": "Не удалось сохранить компаньона.",
    "Could not set the background.": "Не удалось установить фон.",
    "Could not clear the background.": "Не удалось убрать фон.",
    "Home background saved.": "Фон главного меню сохранён.",
    "Home background cleared.": "Фон главного меню убран.",
    "Pick a GIF, MP4 or WebM file.": "Выберите файл GIF, MP4 или WebM.",
    "The selected file was not found.": "Выбранный файл не найден.",
    "The background picker needs Windows.": "Выбор фона доступен только в Windows.",
    "Background": "Фон",
    "LAUNCHER LOG": "ЛОГ ЛАУНЧЕРА",
    "LOGS": "ЛОГИ",
    "Log source": "Источник лога",
    "Every host the launcher tried to reach": "Все серверы, к которым обращался лаунчер",
    "Downloads and what came back. When something fails, copy this report — it shows exactly which host is blocked on this network.": "Загрузки и их результат. Если что-то не работает, скопируйте отчёт — он покажет, какой именно сервер блокирует сеть.",
    "Probe every game host once and see which ones this network can reach. The full event history lives in the Logs section.": "Проверьте все серверы игры и узнайте, какие из них доступны из этой сети. Полная история событий — в разделе «Логи».",
    "Diagnostic log of the launcher itself. It rotates automatically and never contains passwords or account tokens.": "Диагностический лог лаунчера. Он ротируется автоматически и никогда не содержит паролей или токенов аккаунтов.",
    "File": "Файл",
    "NETWORK": "СЕТЬ",
    "Not checked yet": "Проверка не выполнялась",
    "Run the check to see which game hosts this network can reach.": "Запустите проверку, чтобы увидеть, какие серверы игры доступны из этой сети.",
    "Every host the launcher tried to download from and what came back. When something fails, copy this report — it shows exactly which host is blocked on this network.": "Все серверы, с которых лаунчер пытался скачать файлы, и что из этого вышло. Если что-то не работает, скопируйте отчёт — он покажет, какой именно сервер блокирует сеть.",
    "Run check": "Проверить",
    "Copy report": "Скопировать отчёт",
    "Clear log": "Очистить лог",
    "Checking all hosts…": "Проверяем все серверы…",
    "The check could not run": "Не удалось выполнить проверку",
    "Network report copied.": "Отчёт о сети скопирован.",
    "Network log cleared.": "Сетевой лог очищен.",
    "PROXY": "ПРОКСИ",
    "DNS SERVERS": "DNS-СЕРВЕРЫ",
    "Used for downloads, sign-in and updates. Leave empty to use the system connection; localhost and LAN addresses always connect directly. Format: host:port or http://host:port.": "Используется для загрузок, входа и обновлений. Оставьте пустым, чтобы использовать системные настройки подключения; localhost и адреса локальной сети всегда подключаются напрямую. Формат: host:port или http://host:port.",
    "Comma-separated IP addresses. Leave empty for the system DNS. Applies to the launcher only, not the game.": "IP-адреса через запятую. Оставьте пустым для системного DNS. Применяется только к лаунчеру, но не к игре.",
    "System DNS": "Системный DNS",
    "Use the system DNS": "Использовать системный DNS",
    "Could not save the proxy.": "Не удалось сохранить прокси.",
    "Proxy saved.": "Прокси сохранён.",
    "Proxy disabled.": "Прокси отключён.",
    "Could not save the DNS servers.": "Не удалось сохранить DNS-серверы.",
    "DNS servers saved.": "DNS-серверы сохранены.",
    "System DNS restored.": "Системный DNS восстановлен.",
    "Enter a proxy as host:port or http://host:port. Proxies that need a password are not supported.": "Укажите прокси в формате host:port или http://host:port. Прокси с паролем не поддерживаются.",
    "DNS servers must be IP addresses, for example 1.1.1.1, 8.8.8.8.": "DNS-серверы должны быть IP-адресами, например 1.1.1.1, 8.8.8.8.",
    "Use up to three DNS servers.": "Используйте не более трёх DNS-серверов.",
    "CURSEFORGE API KEY": "API-КЛЮЧ CURSEFORGE",
    "Paste a personal API key": "Вставьте личный API-ключ",
    "Saved — paste a new key to replace": "Сохранён — вставьте новый ключ для замены",
    "Get a personal key at console.curseforge.com. It is stored locally in accounts.json and only sent to api.curseforge.com. Without a key, search by pasting a CurseForge project link, numeric ID or exact slug.": "Получите личный ключ на console.curseforge.com. Он хранится локально в accounts.json и отправляется только на api.curseforge.com. Без ключа ищите, вставляя ссылку на проект CurseForge, числовой ID или точный слаг.",
    "Open the CurseForge console →": "Открыть консоль CurseForge →",
    "That does not look like a CurseForge API key.": "Это не похоже на API-ключ CurseForge.",
    "Could not save the CurseForge API key.": "Не удалось сохранить API-ключ CurseForge.",
    "CurseForge API key saved.": "API-ключ CurseForge сохранён.",
    "CurseForge API key cleared.": "API-ключ CurseForge удалён.",
    "No network events yet. Downloads and their failures show up here.": "Событий пока нет. Здесь появятся все загрузки и их ошибки.",
    "Mojang launcher metadata": "Метаданные лаунчера Mojang",
    "Mojang version metadata": "Метаданные версии Mojang",
    "Mojang game files": "Файлы игры Mojang",
    "Mojang libraries": "Библиотеки Mojang",
    "Mojang assets": "Ресурсы Mojang",
    "BMCLAPI mirror": "Зеркало BMCLAPI",
    "Modrinth API": "API Modrinth",
    "Modrinth files": "Файлы Modrinth",
    "CurseForge API": "API CurseForge",
    "CurseForge site": "Сайт CurseForge",
    "CurseForge files": "Файлы CurseForge",
    "CFWidget lookup": "Запросы CFWidget",
    "Fabric maven": "Maven Fabric",
    "Fabric meta": "Метаданные Fabric",
    "Forge maven": "Maven Forge",
    "Forge promotions": "Промо-версии Forge",
    "NeoForge maven": "Maven NeoForge",
    "NeoForge maven (official)": "Maven NeoForge (официальный)",
    "NeoForge maven (BMCLAPI)": "Maven NeoForge (BMCLAPI)",
    "Prism meta (NeoForge fallback)": "Метаданные Prism (резерв NeoForge)",
    "Mojang auth": "Авторизация Mojang",
    "Mojang session server": "Сессии Mojang",
    "Mojang login services": "Сервисы входа Mojang",
    "Mojang skin textures": "Текстуры скинов Mojang",
    "Microsoft sign-in": "Вход Microsoft",
    "Xbox Live auth": "Авторизация Xbox Live",
    "Xbox security token": "Токен безопасности Xbox",
    "Ely.by auth": "Авторизация Ely.by",
    "Ely.by account": "Аккаунт Ely.by",
    "Ely.by skins": "Скины Ely.by",
    "GitHub API (updates)": "API GitHub (обновления)",
    "GitHub release files": "Файлы релизов GitHub",
    /* Host categories */
    "Game files": "Файлы игры",
    "Accounts & skins": "Аккаунты и скины",
    "Loaders": "Загрузчики",
    "Updates": "Обновления",

    /* Bypass (zapret) */
    "BYPASS (ZAPRET)": "ОБХОД (ZAPRET)",
    "DPI bypass": "Обход блокировок DPI",
    "Checking for an installed copy…": "Проверяем, установлен ли zapret…",
    "STRATEGY": "СТРАТЕГИЯ",
    "Enable bypass": "Включить обход",
    "Apply domains again": "Добавить адреса и включить",
    "Download & enable": "Скачать и настроить",
    "Confirm download": "Подтвердить скачивание",
    "Turn the bypass on when the launcher starts": "Включать обход при запуске лаунчера",
    "Something failed to load": "Что-то не загрузилось",
    "Enable bypass and add address": "Включить обход и добавить адрес",
    /* Mirror / bypass choice */
    "MIRROR / BYPASS": "ЗЕРКАЛО / ОБХОД",
    "Automatic — use the mirror only when a host is blocked":
      "Автоматически — зеркало только когда адрес заблокирован",
    "Always use the BMCLAPI mirror": "Всегда использовать зеркало BMCLAPI",
    "Never use the mirror — rely on the bypass":
      "Не использовать зеркало — полагаться на обход",
    "MIRROR OR BYPASS": "ЗЕРКАЛО ИЛИ ОБХОД",
    "Something is blocked on this network": "Часть сети заблокирована",
    "The server did not answer directly, so the launcher switched to the BMCLAPI mirror. Choose what it should do from now on — the choice is saved, and you can change it later in Settings → Network.":
      "Сервер не ответил напрямую, поэтому лаунчер переключился на зеркало BMCLAPI. Выберите, что делать дальше: решение сохранится, и его можно изменить в «Настройки → Сеть».",
    "Always use the mirror": "Всегда использовать зеркало",
    "Downloads go straight to the BMCLAPI mirror. No bypass and no administrator prompt.":
      "Скачивание идёт сразу с зеркала BMCLAPI. Без обхода и без запроса прав администратора.",
    "Always use the bypass": "Всегда использовать обход",
    "Keep the official servers and turn on zapret. The mirror is never used again.":
      "Оставить официальные серверы и включить zapret. Зеркало больше не используется.",
    "Decide automatically every time": "Решать автоматически каждый раз",
    "Not now": "Не сейчас",
    "Uses unsigned third-party binaries (WinDivert). Antivirus may flag them, Windows will ask for administrator rights, and the network may briefly drop while the bypass restarts.": "Используются сторонние неподписанные бинарники (WinDivert). Антивирус может на них ругаться, Windows запросит права администратора, а сеть может на несколько секунд прерваться при перезапуске обхода.",
    "Adds the launcher's hosts to the general list (list-general-user.txt) and turns the bypass on. Existing entries are never duplicated.": "Добавляет адреса лаунчера в общий список (list-general-user.txt) и включает обход. Уже существующие строки не дублируются.",
    "Not checked yet.": "Проверка не выполнялась.",
    "LAUNCHER UPDATE": "ОБНОВЛЕНИЕ ЛАУНЧЕРА",
    "Not checked": "Не проверялось",
    "Up to date": "Последняя версия",
    "Check for updates": "Проверить обновления",
    "Confirm update": "Подтвердить обновление",
    "Restarting…": "Перезапуск…",
    "Check GitHub for a newer release. Accounts, settings and profiles are kept when you update.": "Проверить на GitHub новую версию. При обновлении аккаунты, настройки и сборки сохраняются.",
    "You are running the latest version.": "У вас последняя версия.",
    "Update downloaded. The launcher will close and restart.": "Обновление скачано. Лаунчер закроется и перезапустится.",
    "Update cancelled.": "Обновление отменено.",
    "Could not check for updates.": "Не удалось проверить обновления.",
    "FOLDERS": "ПАПКИ",
    "Shared files": "Общие файлы",
    "Profiles never copy files from the shared folder — versions, libraries and assets are reused in place.": "Сборки никогда не копируют файлы из общей папки — версии, библиотеки и ресурсы используются на месте.",
    "logs\\launcher.log": "logs\\launcher.log",
    "logs/latest.log": "logs/latest.log",

    /* Skins */
    "Skin": "Скин",
    "Sign in to manage your skin.": "Войдите, чтобы управлять скином.",
    "Choose PNG…": "Выбрать PNG…",
    "Apply to account": "Применить к аккаунту",
    "The head follows the cursor; drag the model sideways to spin it.": "Голова следует за курсором; тяните модель вбок, чтобы вращать её.",
    "MODEL": "МОДЕЛЬ",
    "Classic": "Классическая",
    "Slim": "Тонкая",
    "A skin is a 64×64 or 64×32 PNG. The file is stored by the launcher and never sent anywhere except the account you apply it to.": "Скин — это PNG 64×64 или 64×32. Лаунчер хранит файл и отправляет его только тому аккаунту, к которому вы применяете скин.",
    "Change skin on ely.by →": "Сменить скин на ely.by →",
    "Ready.": "Готово.",
    "No account selected": "Аккаунт не выбран",
    "No account": "Нет аккаунта",
    "No accounts": "Нет аккаунтов",
    "Add an account in Settings first.": "Сначала добавьте аккаунт в настройках.",
    "Ely.by keeps skins on its website; the game loads them through authlib-injector.": "Ely.by хранит скины на своём сайте; игра загружает их через authlib-injector.",
    "The skin belongs to this account and shows in every profile.": "Скин принадлежит этому аккаунту и отображается во всех сборках.",
    "Offline accounts cannot use server-side skins.": "Оффлайн-аккаунты не могут использовать серверные скины.",
    "The skin cannot be changed from the launcher. Use the link below to open ely.by/skins, upload the PNG there and it will show up in game.": "Скин нельзя сменить из лаунчера. Откройте по ссылке ниже ely.by/skins, загрузите туда PNG — и он появится в игре.",
    "A skin is a 64×64 or 64×32 PNG. It is stored by the launcher and only sent to the account you apply it to.": "Скин — это PNG 64×64 или 64×32. Лаунчер хранит его и отправляет только тому аккаунту, к которому вы применяете скин.",
    "Offline accounts cannot change their skin. Add a Microsoft or Ely.by account to manage one.": "Оффлайн-аккаунты не могут менять скин. Добавьте аккаунт Microsoft или Ely.by.",
    "Current skin loaded from ely.by": "Текущий скин загружен с ely.by",
    "Built-in default skin — choose a PNG to replace it.": "Встроенный скин по умолчанию — выберите PNG, чтобы заменить его.",
    "No skin chosen yet": "Скин ещё не выбран",
    "SKIN HISTORY": "ИСТОРИЯ СКИНОВ",
    "Skins you pick are kept here so you can switch back.": "Выбранные скины хранятся здесь — к любому можно вернуться.",
    "Skin loaded from history. Press “Apply to account” to send it.": "Скин взят из истории. Нажмите «Применить к аккаунту», чтобы отправить его.",
    "Could not use that skin.": "Не удалось использовать этот скин.",
    "Confirm clear": "Подтвердить очистку",
    "Skin history cleared.": "История скинов очищена.",
    "Could not clear the skin history.": "Не удалось очистить историю скинов.",
    "offline mode · mojang + modrinth": "оффлайн-режим · mojang + modrinth",

    /* Empty-state and misc UI */
    "Edit": "Изменить",
    "Duplicate": "Дублировать",
    "Verify files": "Проверить файлы",
    "This profile is vanilla — install a mod loader first": "Эта сборка ванильная — сначала установите загрузчик модов",
    "This profile is vanilla — install Fabric, Forge or NeoForge to use mods.": "Эта сборка ванильная — установите Fabric, Forge или NeoForge, чтобы использовать моды.",
    "Create a profile to get started.": "Создайте сборку, чтобы начать.",
    "Create or select a profile first.": "Сначала создайте или выберите сборку.",

    /* Attributes */
    "Sections": "Разделы",
    "Import modpack": "Импорт модпака",
    "Browse modpacks": "Обзор модпаков",
    "Profile contents": "Содержимое сборки",
    "Minecraft version": "Версия Minecraft",
    "Less default memory": "Меньше памяти по умолчанию",
    "More default memory": "Больше памяти по умолчанию",
    "Less memory": "Меньше памяти",
    "More memory": "Больше памяти",
    "Launcher theme": "Тема лаунчера",
    "Interface language": "Язык интерфейса",
    "3D skin preview": "3D-просмотр скина",
    "Account whose skin is shown": "Аккаунт, чей скин показан",
    "Profile actions": "Действия со сборкой",
    "My build": "Моя сборка",
    "Search versions": "Поиск версий",
    "Search by name": "Поиск по названию",
    "6-digit code": "6-значный код",
    "Only for Website apps — leave blank for PKCE": "Только для Website-приложений — оставьте пустым для PKCE",
    "Offline player name": "Имя оффлайн-игрока",
    "Automatic — downloaded for each version": "Автоматически — загружается для каждой версии",

    /* Dynamic status messages */
    "Could not remove the mod.": "Не удалось удалить мод.",
    "Mod removed.": "Мод удалён.",
    "Checking installed mods…": "Проверяем установленные моды…",
    "Done.": "Готово.",
    "Profile icon updated.": "Иконка сборки обновлена.",
    "Profile icon removed.": "Иконка сборки удалена.",
    "Enter your Ely.by e-mail/username and password.": "Введите почту/ник и пароль Ely.by.",
    "Signing in to Ely.by…": "Вход в Ely.by…",
    "Ely.by sign-in failed.": "Не удалось войти в Ely.by.",
    "Could not start Ely.by browser sign-in.": "Не удалось запустить вход через браузер Ely.by.",
    "Waiting for Ely.by sign-in in the browser…": "Ждём вход в Ely.by в браузере…",
    "Ely.by browser sign-in cancelled.": "Вход в Ely.by через браузер отменён.",
    "Enter the Ely.by OAuth Client ID.": "Введите OAuth Client ID Ely.by.",
    "Could not save the OAuth settings.": "Не удалось сохранить настройки OAuth.",
    "Browser sign-in is ready. Press “Sign in with browser”.": "Вход через браузер готов. Нажмите «Войти через браузер».",
    "Saved. Add the Ely.by Client ID before browser sign-in works.": "Сохранено. Добавьте Client ID Ely.by, чтобы включить вход через браузер.",
    "Could not switch accounts.": "Не удалось переключить аккаунт.",
    "Could not change the account.": "Не удалось сменить аккаунт.",
    "Active account switched.": "Активный аккаунт переключён.",
    "Could not reorder accounts.": "Не удалось изменить порядок аккаунтов.",
    "Could not save the theme.": "Не удалось сохранить тему.",
    "Could not save the colour mode.": "Не удалось сохранить цветовую тему.",
    "Could not save the language.": "Не удалось сохранить язык.",
    "Colour mode: Dark.": "Цветовая тема: тёмная.",
    "Colour mode: Light.": "Цветовая тема: светлая.",
    "Language: English.": "Язык: English.",
    "Language: Русский.": "Язык: Русский.",
    "Theme: Mint.": "Тема: Мята.",
    "Theme: Soft orange.": "Тема: Мягкий оранжевый.",
    "Theme: Indigo.": "Тема: Индиго.",
    "Could not remove the account.": "Не удалось удалить аккаунт.",
    "Account removed.": "Аккаунт удалён.",
    "Type an offline player name first.": "Сначала введите имя оффлайн-игрока.",
    "Could not add the account.": "Не удалось добавить аккаунт.",
    "Could not save the Client ID.": "Не удалось сохранить Client ID.",
    "Client ID saved.": "Client ID сохранён.",
    "Client ID cleared.": "Client ID очищен.",
    "Could not start Microsoft sign-in.": "Не удалось запустить вход Microsoft.",
    "Waiting for Microsoft sign-in…": "Ждём вход Microsoft…",
    "Microsoft sign-in cancelled.": "Вход Microsoft отменён.",
    "Java set to automatic.": "Java: автоматический выбор.",
    "That Java path is not valid.": "Этот путь к Java недействителен.",
    "Could not set Java.": "Не удалось задать Java.",
    "Could not start the game.": "Не удалось запустить игру.",
    "Stopping the game…": "Останавливаем игру…",
    "Could not stop the game.": "Не удалось остановить игру.",
    "Game stopped.": "Игра остановлена.",
    "Game started.": "Игра запущена.",
    "Restarting the game…": "Перезапускаем игру…",
    "Could not restart the game.": "Не удалось перезапустить игру.",
    "Pick a Minecraft version first.": "Сначала выберите версию Minecraft.",
    "Pick a loader version first.": "Сначала выберите версию загрузчика.",
    "Updating the profile — files may be downloaded…": "Обновляем сборку — возможно, скачиваются файлы…",
    "Copying the profile — worlds and logs are skipped…": "Копируем сборку — миры и логи пропускаются…",
    "Packing the worlds…": "Упаковываем миры…",
    "Checking game files — this can take a minute…": "Проверяем файлы игры — это может занять минуту…",
    "Import cancelled.": "Импорт отменён.",
    "Could not open the file picker.": "Не удалось открыть выбор файла.",
    "Importing the modpack — this can take a few minutes…": "Импортируем модпак — это может занять несколько минут…",
    "Modpack imported.": "Модпак импортирован.",
    "Could not import the modpack.": "Не удалось импортировать модпак.",
    "Modpack installed.": "Модпак установлен.",
    "Choose a skin PNG…": "Выберите PNG со скином…",
    "Could not use that image.": "Не удалось использовать это изображение.",
    "Skin saved. Press “Apply to account” to send it.": "Скин сохранён. Нажмите «Применить к аккаунту».",
    "Could not save the model.": "Не удалось сохранить модель.",
    "Uploading the skin…": "Загружаем скин…",
    "Skin upload failed.": "Не удалось загрузить скин.",
    "Skin applied.": "Скин применён.",
    "Enter the sign-in code in the browser to finish.": "Введите код входа в браузере, чтобы завершить.",
    "Microsoft sign-in failed.": "Не удалось войти в Microsoft.",
    "Microsoft account removed.": "Аккаунт Microsoft удалён.",
    "Ely.by browser sign-in failed.": "Не удалось войти в Ely.by через браузер.",
    "Select a Minecraft version first.": "Сначала выберите версию Minecraft.",
    "Saving changes…": "Сохраняем изменения…",
    "Creating…": "Создаём…",
    "Cancelled — the profile was not changed.": "Отменено — сборка не изменена.",
    "Cancelled — no profile was created.": "Отменено — сборка не создана.",
    "Could not update the profile.": "Не удалось обновить сборку.",
    "Could not create the profile.": "Не удалось создать сборку.",
    "Nothing found — try another name": "Ничего не найдено — попробуйте другое название",
    "Nothing found — try another name or loader": "Ничего не найдено — попробуйте другое название или загрузчик",
    "Profile settings are unchanged.": "Настройки сборки не изменены.",
    "Verification cancelled.": "Проверка отменена.",

    /* First-run setup */
    "launcher setup": "настройка лаунчера",
    "Skip setup": "Пропустить настройку",
    "FIRST START": "ПЕРВЫЙ ЗАПУСК",
    "Welcome to Nexi Launcher": "Добро пожаловать в Nexi Launcher",
    "A few quick choices and you are ready to play.": "Пара быстрых настроек — и можно играть.",
    "Interface language": "Язык интерфейса",
    "Theme and colour mode": "Тема и режим оформления",
    "Network bypass for blocked Minecraft servers": "Обход блокировок для серверов Minecraft",
    "LANGUAGE": "ЯЗЫК",
    "Choose your language": "Выберите язык",
    "The interface changes right away; everything else follows.": "Интерфейс переключится сразу, остальное — следом.",
    "APPEARANCE": "ОФОРМЛЕНИЕ",
    "Make it yours": "Настройте под себя",
    "Pick an accent colour and a colour mode.": "Выберите акцентный цвет и режим оформления.",
    "Accent colour": "Акцентный цвет",
    "Colour mode": "Режим оформления",
    "Dark is the default; light switches to white surfaces.": "Тёмный — по умолчанию; светлый переключает на белые поверхности.",
    "BYPASS": "ОБХОД",
    "Network bypass (zapret)": "Обход блокировок (zapret)",
    "Minecraft servers and mod sites are often blocked by the provider. The bypass brings them back.": "Провайдеры часто блокируют серверы Minecraft и сайты модов. Обход возвращает к ним доступ.",
    "Checking for zapret…": "Ищем zapret…",
    "zapret and WinDivert are third-party unsigned binaries. Windows asks for administrator rights and some antivirus tools flag them. You can skip this step and enable the bypass later in the Bypass tab.": "zapret и WinDivert — сторонние неподписанные программы. Windows запросит права администратора, а некоторые антивирусы могут на них ругаться. Шаг можно пропустить и включить обход позже на вкладке «Обход».",
    "Turn the bypass on": "Включить обход",
    "Download and enable": "Скачать и включить",
    "Back": "Назад",
    "Get started": "Начать",
    "Continue": "Продолжить",
    "Finish": "Готово",
    "Setup skipped — everything can be changed in Settings.": "Настройка пропущена — всё можно изменить в «Настройках».",
    "Ready.": "Готово.",
    "Could not check for zapret.": "Не удалось проверить zapret.",
    "zapret is not installed on this computer.": "zapret не установлен на этом компьютере.",
    "Turning the bypass on… Confirm the Windows administrator prompt.": "Включаем обход… Подтвердите запрос прав администратора Windows.",
    "Downloading zapret and turning the bypass on… Confirm the Windows administrator prompt.": "Скачиваем zapret и включаем обход… Подтвердите запрос прав администратора Windows.",
    "Could not run the bypass.": "Не удалось запустить обход.",
    "The bypass is running. You can change it later in the Bypass tab.": "Обход включён. Изменить его можно позже на вкладке «Обход».",
    "Cancelled — the bypass was not changed.": "Отменено — обход не изменён.",
    "zapret is not installed. Use “Download and enable” to install it.": "zapret не установлен. Нажмите «Скачать и включить», чтобы установить его.",
    "Could not turn the bypass on.": "Не удалось включить обход.",

    /* First-run game and performance defaults */
    "PERFORMANCE & GAME": "ПРОИЗВОДИТЕЛЬНОСТЬ И ИГРА",
    "Tune Minecraft": "Настройте Minecraft",
    "These values are saved as defaults for new profiles and written into options.txt before every launch.": "Эти значения сохранятся как настройки по умолчанию для новых сборок и будут записываться в options.txt перед каждым запуском.",
    "Automatic setup": "Автоматическая настройка",
    "Auto-configure": "Настроить автоматически",
    "PERFORMANCE": "ПРОИЗВОДИТЕЛЬНОСТЬ",
    "GAME": "ИГРА",
    "MEMORY": "ПАМЯТЬ",
    "FIELD OF VIEW": "УГОЛ ОБЗОРА",
    "Checking this computer…": "Проверяем компьютер…",
    "Could not detect this computer — pick the values manually.": "Не удалось определить параметры компьютера — выберите значения вручную.",
    "Memory size was not detected — choose how much RAM Minecraft should use.": "Объём памяти не определён — выберите, сколько ОЗУ выделить Minecraft.",
    "FIRST-RUN SETUP": "ПЕРВЫЙ ЗАПУСК",
    "Run the welcome screen again": "Открыть экран приветствия снова",
    "Review the language, appearance, network bypass and Minecraft defaults chosen at first launch. Nothing is reset.": "Ещё раз пройдите выбор языка, оформления, обхода блокировок и настроек Minecraft, сделанный при первом запуске. Ничего не сбрасывается.",
    "Open welcome screen": "Открыть приветствие",

    /* Site-initiated Minecraft account link */
    "Link a Minecraft account?": "Привязать аккаунт Minecraft?",
    "Link account": "Привязать аккаунт",
    "Choose an account in the launcher window.": "Выберите аккаунт в окне лаунчера.",
    "No Microsoft or Ely.by account is signed in here. Sign in under Settings → Accounts, then start the link again.": "Здесь нет аккаунтов Microsoft или Ely.by со входом. Войдите в «Настройки → Аккаунты» и начните привязку снова.",
    "Linking…": "Привязываем…",
    "Could not link the Minecraft account.": "Не удалось привязать Minecraft-аккаунт.",
    "Could not start linking the Minecraft account.": "Не удалось начать привязку Minecraft-аккаунта.",
    "Links your Minecraft account through the Nexi site. The site opens the launcher and asks which Microsoft or Ely.by account you are signed in with.": "Привязывает Minecraft-аккаунт через сайт Nexi. Сайт открывает лаунчер и спрашивает, под каким аккаунтом Microsoft или Ely.by вы вошли.",
  };

  const ATTRS = ["placeholder", "title", "aria-label"];

  const plural = (n, one, few, many) => {
    const mod10 = Math.abs(n) % 10;
    const mod100 = Math.abs(n) % 100;
    if (mod10 === 1 && mod100 !== 11) return one;
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few;
    return many;
  };

  const noun = (word, n) => {
    if (word === "mods" || word === "mod") {
      return plural(n, "мод", "мода", "модов");
    }
    if (word === "resource packs" || word === "resource pack") {
      return plural(n, "ресурспак", "ресурспака", "ресурспаков");
    }
    if (word === "shaders" || word === "shader pack") {
      return plural(n, "шейдерпак", "шейдерпака", "шейдерпаков");
    }
    if (word === "modpacks" || word === "modpack") {
      return plural(n, "модпак", "модпака", "модпаков");
    }
    if (word === "worlds" || word === "world") {
      return plural(n, "мир", "мира", "миров");
    }
    if (word === "screenshots" || word === "screenshot") {
      return plural(n, "скриншот", "скриншота", "скриншотов");
    }
    return word;
  };

  const sectionName = (word) => ({
    "mods": "моды",
    "resource packs": "ресурспаки",
    "shaders": "шейдеры",
    "modpacks": "модпаки",
  }[word] || word);

  const RULES = [
    [/^Memory for “(.*)”$/, (m) => `Память для «${m[1]}»`],
    [/^Link a Minecraft account to Nexi ID (.+?)\? Choose the account you are signed in with — it will be saved on the site\.$/, (m) =>
      `Привязать аккаунт Minecraft к Nexi ID ${m[1]}? Выберите аккаунт, под которым вы вошли, — он сохранится на сайте.`],
    /* Launcher update */
    [/^Not checked$/, () => "Не проверялось"],
    [/^Up to date$/, () => "Последняя версия"],
    [/^Updating…$/, () => "Обновляем…"],
    [/^Updating… (\d+)%$/, (m) => `Обновляем… ${m[1]}%`],
    [/^Restarting…$/, () => "Перезапуск…"],
    [/^(v[\d.]+) available$/, (m) => `Доступна ${m[1]}`],
    [/^Update to (v[\d.]+)$/, (m) => `Обновить до ${m[1]}`],
    [/^You are running the latest version \((.+)\)\.$/, (m) =>
      `У вас последняя версия (${m[1]}).`],
    [/^Nexi Launcher (v[\d.]+) is available\.$/, (m) =>
      `Доступна Nexi Launcher ${m[1]}.`],
    [/^Nexi Launcher (v[\d.]+) is available\. Press Update to install it — the launcher will restart, and accounts, settings and profiles are kept\.$/, (m) =>
      `Доступна Nexi Launcher ${m[1]}. Нажмите «Обновить» — лаунчер перезапустится, аккаунты, настройки и сборки сохранятся.`],
    [/^Click Update again to download Nexi Launcher (v[\d.]+) and restart the launcher\.$/, (m) =>
      `Нажмите «Обновить» ещё раз, чтобы скачать Nexi Launcher ${m[1]} и перезапустить лаунчер.`],
    [/^Downloading Nexi Launcher (v[\d.]+)…$/, (m) =>
      `Скачиваем Nexi Launcher ${m[1]}…`],
    [/^Could not check for updates: (.+)$/, (m) =>
      `Не удалось проверить обновления: ${m[1]}`],
    [/^Update failed\.$/, () => "Не удалось обновить."],
    /* Bypass (zapret) */
    [/^(.+) · service running(?: · (.+))?$/, (m) =>
      `${m[1]} · служба запущена${m[2] ? ` · ${m[2]}` : ""}`],
    [/^(.+) · service stopped(?: · (.+))?$/, (m) =>
      `${m[1]} · служба остановлена${m[2] ? ` · ${m[2]}` : ""}`],
    [/^(.+) · running(?: · (.+))?$/, (m) =>
      `${m[1]} · работает${m[2] ? ` · ${m[2]}` : ""}`],
    [/^(.+) · not running$/, (m) => `${m[1]} · не работает`],
    [/^Not installed$/, () => "Не установлен"],
    [/^not found$/, () => "не найден"],
    [/^zapret found · bypass is running \((.+)\)\.$/, (m) =>
      `zapret найден · обход включён (${m[1]}).`],
    [/^zapret found · bypass is running\.$/, () =>
      "zapret найден · обход включён."],
    [/^zapret found in (.+) · the bypass is not running\.$/, (m) =>
      `zapret найден в ${m[1]} · обход не включён.`],
    [/^Checking…$/, () => "Проверяем…"],
    [/^zapret was not found\. Downloading puts it in the launcher's data folder and configures the general list automatically\.$/, () =>
      "zapret не найден. При скачивании он попадёт в папку данных лаунчера, а общий список настроится автоматически."],
    [/^The zapret service is running, but its folder could not be read\. Choose the folder manually\.$/, () =>
      "Служба zapret запущена, но её папку прочитать не удалось. Укажите папку вручную."],
    [/^(\d+) launcher address\(es\) missing from (.+)\.$/, (m) =>
      `В ${m[2]} не хватает адресов лаунчера: ${m[1]}.`],
    [/^All launcher addresses are already in (.+)\.$/, (m) =>
      `Все адреса лаунчера уже есть в ${m[1]}.`],
    [/^Using (.+)\.$/, (m) => `Используется ${m[1]}.`],
    [/^Strategy: (.+)\.$/, (m) => `Стратегия: ${m[1]}.`],
    [/^Click again to download the latest zapret release and configure it\.$/, () =>
      "Нажмите ещё раз, чтобы скачать свежий релиз zapret и настроить его."],
    [/^Click again to confirm\.$/, () => "Нажмите ещё раз для подтверждения."],
    [/^Downloading zapret — confirm the administrator prompt…$/, () =>
      "Скачиваем zapret — подтвердите запрос прав администратора…"],
    [/^Applying the list — confirm the administrator prompt…$/, () =>
      "Применяем список — подтвердите запрос прав администратора…"],
    [/^Adding the failed address and turning the bypass on — confirm the administrator prompt…$/, () =>
      "Добавляем адрес, который не загрузился, и включаем обход — подтвердите запрос прав администратора…"],
    [/^(.+) did not load\. Add (these addresses|this address) to the bypass list and turn the bypass on\?$/, (m) =>
      `${m[1]} не загрузилось. Добавить ${m[2] === "this address" ? "этот адрес" : "эти адреса"} в список обхода и включить его?`],
    [/^The bypass will start together with the launcher\.$/, () =>
      "Обход будет включаться вместе с лаунчером."],
    [/^The bypass will not start automatically\.$/, () =>
      "Обход больше не будет включаться автоматически."],
    /* Mirror / bypass choice */
    [/^(.+) is blocked on this network\. Choose how the launcher should download from now on\.$/, (m) =>
      `${m[1]} заблокирован в этой сети. Как лаунчеру скачивать дальше?`],
    [/^A download server is blocked on this network\. Choose how the launcher should download from now on\.$/, () =>
      "Сервер загрузки заблокирован в этой сети. Как лаунчеру скачивать дальше?"],
    [/^The launcher will pick the mirror automatically\.$/, () =>
      "Лаунчер будет сам выбирать зеркало при необходимости."],
    [/^The launcher will always use the BMCLAPI mirror\.$/, () =>
      "Лаунчер всегда будет использовать зеркало BMCLAPI."],
    [/^The launcher will never use the mirror\.$/, () =>
      "Лаунчер больше не будет использовать зеркало."],
    [/^Saving the choice…$/, () => "Сохраняем выбор…"],
    [/^The choice could not be saved\.$/, () => "Не удалось сохранить выбор."],
    [/^Checking the bypass…$/, () => "Проверяем обход…"],
    [/^Turning the bypass on — confirm the administrator prompt…$/, () =>
      "Включаем обход — подтвердите запрос прав администратора…"],
    [/^The bypass is on; the mirror will not be used\.$/, () =>
      "Обход включён; зеркало больше не будет использоваться."],
    [/^Confirm the zapret download in the Bypass tab to use the bypass\.$/, () =>
      "Подтвердите скачивание zapret на вкладке «Обход», чтобы использовать обход."],
    [/^Could not turn the bypass on\.$/, () => "Не удалось включить обход."],
    [/^Stopping the bypass…$/, () => "Останавливаем обход…"],
    [/^Looking for zapret…$/, () => "Ищем zapret…"],
    [/^Downloading zapret…$/, () => "Скачиваем zapret…"],
    [/^Downloading the latest zapret release from GitHub…$/, () =>
      "Скачиваем последний релиз zapret с GitHub…"],
    [/^Turning the bypass on…$/, () => "Включаем обход…"],
    [/^Applying the list and \(re\)starting the bypass — confirm the Windows administrator prompt…$/, () =>
      "Применяем список и перезапускаем обход — подтвердите запрос администратора Windows…"],
    [/^zapret (.+) unpacked\.$/, (m) => `zapret ${m[1]} распакован.`],
    [/^Added (\d+) address\(es\) to (.+)\.$/, (m) =>
      `Добавлено адресов в ${m[2]}: ${m[1]}.`],
    [/^(.+) already contains every launcher address\.$/, (m) =>
      `В ${m[1]} уже есть все адреса лаунчера.`],
    [/^Bypass is running \((.+)\); added (\d+) address\(es\)\.$/, (m) =>
      `Обход включён (${m[1]}); добавлено адресов: ${m[2]}.`],
    [/^Bypass is running \((.+)\)\.$/, (m) => `Обход включён (${m[1]}).`],
    [/^Bypass stopped\.$/, () => "Обход остановлен."],
    [/^Cancelled\.$/, () => "Отменено."],
    [/^Cancelled\. The elevated step may still finish in the background\.$/, () =>
      "Отменено. Шаг с правами администратора может ещё завершиться в фоне."],
    [/^Administrator rights were not granted\.$/, () =>
      "Права администратора не выданы."],
    [/^Could not start the elevated helper \(code (\d+)\)\.$/, (m) =>
      `Не удалось запустить процесс с правами администратора (код ${m[1]}).`],
    [/^The elevated helper exited without a result\. Run it again; if it keeps failing, check the log\.$/, () =>
      "Процесс с правами администратора завершился без результата. Запустите ещё раз; если это повторяется, проверьте журнал."],
    [/^The elevated helper did not finish\. Check whether the Windows prompt is still open\.$/, () =>
      "Процесс с правами администратора не завершился. Проверьте, не висит ли запрос прав администратора Windows."],
    [/^Another zapret instance is running from a different folder\. Stop it first\.$/, () =>
      "Другой экземпляр zapret запущен из другой папки. Сначала остановите его."],
    [/^The zapret service did not start\.$/, () =>
      "Служба zapret не запустилась."],
    [/^Preset not found: (.+)$/, (m) => `Пресет не найден: ${m[1]}`],
    [/^winws\.exe did not start\. Check the strategy and antivirus\.$/, () =>
      "winws.exe не запустился. Проверьте стратегию и антивирус."],
    [/^ERROR: winws\.exe did not start\. Check the strategy and antivirus\.$/, () =>
      "ОШИБКА: winws.exe не запустился. Проверьте стратегию и антивирус."],
    [/^ERROR: Another zapret instance is running from a different folder\. Stop it first\.$/, () =>
      "ОШИБКА: другой экземпляр zapret запущен из другой папки. Сначала остановите его."],
    [/^ERROR: The zapret service did not start\.$/, () =>
      "ОШИБКА: служба zapret не запустилась."],
    [/^ERROR: Preset not found: (.+)$/, (m) => `ОШИБКА: пресет не найден: ${m[1]}`],
    [/^ERROR: (.+)$/, (m) => `ОШИБКА: ${m[1]}`],
    [/^list: added (\d+) domain\(s\)$/, (m) =>
      `список: добавлено адресов: ${m[1]}`],
    [/^helper started$/, () => "служебный процесс запущен"],
    [/^list: nothing to add$/, () => "список: добавлять нечего"],
    [/^service: Running$/, () => "служба: запущена"],
    [/^service: Stopped$/, () => "служба: остановлена"],
    [/^service stopped$/, () => "служба остановлена"],
    [/^service started$/, () => "служба запущена"],
    [/^stop failed: (.+)$/, (m) => `остановить не удалось: ${m[1]}`],
    [/^winws stopped$/, () => "winws остановлен"],
    [/^preset started: (.+)$/, (m) => `стратегия запущена: ${m[1]}`],
    [/^Cancelling…$/, () => "Отменяем…"],
    [/^Could not configure zapret: (.+)$/, (m) =>
      `Не удалось настроить zapret: ${m[1]}`],
    [/^Could not turn the bypass on\.$/, () => "Не удалось включить обход."],
    [/^Could not stop the bypass\.$/, () => "Не удалось остановить обход."],
    [/^(.*) — Minecraft (.*) · vanilla$/, (m) =>
      `${m[1]} — Minecraft ${m[2]} · ванильная`],
    [/^Minecraft (.+) · vanilla$/, (m) => `Minecraft ${m[1]} · ванильная`],
    [/^(.+) · Minecraft (.+) · currently vanilla$/, (m) =>
      `${m[1]} · Minecraft ${m[2]} · сейчас ванильная`],
    [/^Searching (Modrinth|CurseForge)…$/, (m) => `Поиск в ${m[1]}…`],
    [/^(Modrinth|CurseForge) · (mods|resource packs|shaders|modpacks)( · .*)?$/, (m) =>
      `${m[1]} · ${sectionName(m[2])}${(m[3] || "")
        .replace("all versions", "все версии")
        .replace("any loader", "любой загрузчик")
        .replace("installs as a new profile", "устанавливаются как новая сборка")}`],
    [/^(.*) · Offline — unavailable$/, (m) =>
      `${m[1]} · оффлайн — недоступен`],
    [/^(.*) · Offline$/, (m) => `${m[1]} · оффлайн`],
    [/^Launcher default · (.*)$/, (m) => `Как в настройках · ${m[1]}`],
    [/^Uses the active account: (.*)$/, (m) =>
      `Используется активный аккаунт: ${m[1]}`],
    [/^(\d+) total$/, (m) => `${m[1]} всего`],
    [/^(\d+) versions — pick one$/, (m) =>
      `${m[1]} ${plural(+m[1], "версия", "версии", "версий")} — выберите одну`],
    [/^(\d+) builds found — press Install loader$/, (m) =>
      `Найдено ${m[1]} ${plural(+m[1], "сборка", "сборки", "сборок")} — нажмите «Установить загрузчик»`],
    [/^(\d+) (Fabric|Forge|NeoForge) builds found\.$/, (m) =>
      `Найдено ${m[1]} ${plural(+m[1], "сборка", "сборки", "сборок")} ${m[2]}.`],
    [/^Looking up (.+) builds for (.+)…$/, (m) =>
      `Ищем сборки ${m[1]} для ${m[2]}…`],
    [/^Looking up (.+) builds for (.+)… \((\d+:\d+)\)$/, (m) =>
      `Ищем сборки ${m[1]} для ${m[2]}… (${m[3]})`],
    [/^Installing (.+) for (.+)…$/, (m) =>
      `Устанавливаем ${m[1]} для ${m[2]}…`],
    [/^Installing (.+) for (.+)… \((\d+:\d+)\)$/, (m) =>
      `Устанавливаем ${m[1]} для ${m[2]}… (${m[3]})`],
    [/^Downloading Minecraft (.+)…$/, (m) =>
      `Скачиваем Minecraft ${m[1]}…`],
    [/^Installed (.+) — this profile now runs "(.+)"$/, (m) =>
      `Установлено: ${m[1]} — эта сборка теперь запускает «${m[2]}»`],
    [/^No (.+) builds for (.+) — try another loader or Refresh\.$/, (m) =>
      `Нет сборок ${m[1]} для ${m[2]} — попробуйте другой загрузчик или «Обновить».`],
    [/^No (.+) builds for (.+) — try another loader\.$/, (m) =>
      `Нет сборок ${m[1]} для ${m[2]} — попробуйте другой загрузчик.`],
    [/^(.+) is unreachable — the build list came from the BMCLAPI mirror\.$/, (m) =>
      `${m[1]} недоступен — список сборок получен с зеркала BMCLAPI.`],
    [/^Could not list builds: maven\.neoforged\.net is unreachable; set Settings → Network → Mirror to Auto, or add the host to the bypass in the Bypass tab\.$/, () =>
      "Не удалось получить список сборок: maven.neoforged.net недоступен. Включите зеркало в «Настройки → Сеть» или добавьте хост в обход на вкладке «Обход»."],
    [/^Install failed: maven\.neoforged\.net is unreachable; set Settings → Network → Mirror to Auto, or add the host to the bypass in the Bypass tab\.$/, () =>
      "Ошибка установки: maven.neoforged.net недоступен. Включите зеркало в «Настройки → Сеть» или добавьте хост в обход на вкладке «Обход»."],
    [/^Could not list builds: The NeoForge build list could not be read: (.*)$/, (m) =>
      `Не удалось получить список сборок: не удалось прочитать список сборок NeoForge: ${m[1]}`],
    [/^Could not list builds: (.*)$/, (m) =>
      `Не удалось получить список сборок: ${m[1]}`],
    [/^Could not load the Mojang version list: (.*)$/, (m) =>
      `Не удалось загрузить список версий Mojang: ${m[1]}`],
    [/^(\d+) of (\d+) (mods|resource packs|shaders|modpacks)$/, (m) =>
      `${m[1]} из ${m[2]} ${noun(m[3], +m[2])}`],
    [/^(\d+) downloads$/, (m) =>
      `${m[1]} ${plural(+m[1], "загрузка", "загрузки", "загрузок")}`],
    [/^Install selected \((\d+)\)$/, (m) => `Установить выбранные (${m[1]})`],
    [/^Downloading (.*) \((\d+)\/(\d+)\)…$/, (m) =>
      `Скачиваем ${m[1]} (${m[2]}/${m[3]})…`],
    [/^Installed (\d+) of (\d+) — (.*)$/, (m) =>
      `Установлено ${m[1]} из ${m[2]} — ${m[3]}`],
    [/^Installed (\d+) (item|items)\.$/, (m) =>
      `Установлено ${m[1]} ${plural(+m[1], "элемент", "элемента", "элементов")}.`],
    [/^Preparing (.*) — this can take a while…$/, (m) =>
      `Подготавливаем ${m[1]} — это может занять время…`],
    [/^Preparing (.*)…$/, (m) => `Подготавливаем ${m[1]}…`],
    [/^Removing (.*)…$/, (m) => `Удаляем ${m[1]}…`],
    [/^Checking (.*)…$/, (m) => `Проверяем ${m[1]}…`],
    [/^(\d+) (mods?|resource packs?|shader packs?|worlds?|screenshots?) in this profile$/, (m) =>
      `${m[1]} ${noun(m[2], +m[1])} в этой сборке`],
    [/^Theme: (.*)\.$/, (m) => `Тема: ${m[1]}.`],
    [/^(\d+) of (\d+) hosts unreachable$/, (m) =>
      `${m[1]} из ${m[2]} серверов недоступны`],
    [/^All (\d+) hosts reachable$/, (m) =>
      `Все ${m[1]} серверов доступны`],
    [/^Colour mode: (.*)\.$/, (m) => `Цветовая тема: ${m[1]}.`],
    [/^Language: (.*)\.$/, (m) => `Язык: ${m[1]}.`],
    [/^Companion: (.*)\.$/, (m) => `Компаньон: ${m[1]}.`],
    [/^Removed (.*)\.$/, (m) => `${m[1]} удалён.`],
    [/^Signed in to Ely.by as (.*)\.$/, (m) => `Вход в Ely.by выполнен: ${m[1]}.`],
    [/^Signed in as (.*)\.$/, (m) => `Вход выполнен: ${m[1]}.`],
    [/^Offline account “(.*)” is active\.$/, (m) =>
      `Активен оффлайн-аккаунт «${m[1]}».`],
    [/^Starting "(.*)"…$/, (m) => `Запускаем «${m[1]}»…`],
    /* Home */
    [/^Starting "(.*)" in "(.*)"…$/, (m) =>
      `Запускаем «${m[1]}» в мире «${m[2]}»…`],
    [/^Play "(.*)"$/, (m) => `Играть: «${m[1]}»`],
    [/^Selected "(.*)" — Play starts it\.$/, (m) =>
      `Выбрана сборка «${m[1]}» — «Играть» запустит её.`],
    [/^Play (.+)$/, (m) => `Играть: ${m[1]}`],
    [/^Continue in "(.*)"$/, (m) => `Продолжить в «${m[1]}»`],
    [/^just now$/, "только что"],
    [/^(\d+) h(?: (\d+) min)?$/, (m) =>
      m[2] ? `${m[1]} ч ${m[2]} мин` : `${m[1]} ч`],
    [/^(\d+) min$/, (m) => `${m[1]} мин`],
    [/^(\d+) min ago$/, (m) =>
      `${m[1]} ${plural(+m[1], "минуту", "минуты", "минут")} назад`],
    [/^(\d+) h ago$/, (m) => `${m[1]} ч назад`],
    [/^(\d+) d ago$/, (m) => `${m[1]} дн назад`],
    [/^Java set: (.*)$/, (m) => `Java: ${m[1]}`],
    [/^Press Delete again to permanently remove "(.*)" — its worlds, mods and configs are deleted, shared versions stay\.$/, (m) =>
      `Нажмите «Удалить» ещё раз, чтобы навсегда удалить «${m[1]}» — миры, моды и конфиги будут стёрты, общие версии останутся.`],
    [/^Remove (.*)$/, (m) => `Удалить ${m[1]}`],
    [/^Updated to (.*)\.$/, (m) => `Обновлено до ${m[1]}.`],
    [/^Updated (\d+) mod\(s\)(.*)$/, (m) =>
      `Обновлено ${m[1]} ${plural(+m[1], "мод", "мода", "модов")}${m[2]}`],
    [/^Select a profile to manage its (.*)\.$/, (m) =>
      `Выберите сборку, чтобы управлять: ${sectionName(m[1])}.`],
    [/^Select a profile to browse (.*)\.$/, (m) =>
      `Выберите сборку для обзора: ${sectionName(m[1])}.`],
    [/^Select a profile to manage (.*)\.$/, (m) =>
      `Выберите сборку, чтобы управлять: ${sectionName(m[1])}.`],
    /* Messages produced by the Python backend. */
    [/^Created "(.*)"\.$/, (m) => `Создана сборка «${m[1]}».`],
    [/^Created "(.*)" with (.*)$/, (m) =>
      `Создана сборка «${m[1]}» с ${m[2]}`],
    [/^Profile "(.*)" was created, but (.*)$/, (m) =>
      `Сборка «${m[1]}» создана, но ${m[2]}`],
    [/^Renamed to "(.*)"\.$/, (m) => `Переименовано в «${m[1]}».`],
    [/^"(.*)" now uses the active account from Settings\.$/, (m) =>
      `«${m[1]}» использует активный аккаунт из настроек.`],
    [/^"(.*)" now signs in as (.*)\.$/, (m) =>
      `«${m[1]}» теперь входит как ${m[2]}.`],
    [/^"(.*)" now runs Minecraft (.*) with (.*)\.$/, (m) =>
      `«${m[1]}» теперь запускает Minecraft ${m[2]} с ${m[3]}.`],
    [/^"(.*)" now runs Minecraft (.*)\.$/, (m) =>
      `«${m[1]}» теперь запускает Minecraft ${m[2]}.`],
    [/^Duplicated "(.*)" as "(.*)" — (.*)$/, (m) =>
      `Сборка «${m[1]}» скопирована как «${m[2]}» — ${m[3]}`],
    [/^Checked (\d+) files — re-downloaded (\d+) (.*)$/, (m) =>
      `Проверено ${m[1]} ${plural(+m[1], "файл", "файла", "файлов")} — заново скачано ${m[2]} ${plural(+m[2], "файл", "файла", "файлов")}`],
    [/^Checked (\d+) files — everything is intact\.$/, (m) =>
      `Проверено ${m[1]} ${plural(+m[1], "файл", "файла", "файлов")} — всё на месте.`],
    [/^Backed up (\d+) world\(s\) to (.*)$/, (m) =>
      `Сохранено ${m[1]} ${plural(+m[1], "мир", "мира", "миров")} в ${m[2]}`],
    [/^Imported "(.*)" — Minecraft (.*)$/, (m) =>
      `Импортирована сборка «${m[1]}» — Minecraft ${m[2]}`],
    [/^Import cancelled — the partial profile was removed\.$/,
      "Импорт отменён — частичная сборка удалена."],
    [/^Installed: (.*)$/, (m) => `Установлено: ${m[1]}`],
    [/^Install failed: (.*)$/, (m) => `Ошибка установки: ${m[1]}`],
    [/^Update failed: (.*)$/, (m) => `Ошибка обновления: ${m[1]}`],
    [/^Could not install (.*): (.*)$/, (m) =>
      `Не удалось установить ${m[1]}: ${m[2]}`],
    [/^Could not delete (.*): (.*)$/, (m) =>
      `Не удалось удалить ${m[1]}: ${m[2]}`],
    [/^Could not verify the files: (.*)$/, (m) =>
      `Не удалось проверить файлы: ${m[1]}`],
    [/^Could not duplicate the profile: (.*)$/, (m) =>
      `Не удалось скопировать сборку: ${m[1]}`],
    [/^Could not update the profile: (.*)$/, (m) =>
      `Не удалось обновить сборку: ${m[1]}`],
    [/^Could not import the modpack: (.*)$/, (m) =>
      `Не удалось импортировать модпак: ${m[1]}`],
    [/^Could not back up the worlds\.?$/, "Не удалось сохранить резервную копию миров."],
    [/^Could not copy the background: (.*)$/, (m) =>
      `Не удалось скопировать фон: ${m[1]}`],
    [/^(.*) is already up to date\.$/, (m) => `${m[1]} уже обновлён.`],
    [/^(.*) is already installed\.$/, (m) => `${m[1]} уже установлен.`],
    [/^Installed (.*)\.$/, (m) => `${m[1]} установлен.`],
    [/^(.*) is running\.$/, (m) => `${m[1]} запущена.`],
    [/^Invalid Ely\.by e-mail\/username or password\.$/,
      "Неверная почта/ник или пароль Ely.by."],
    [/^Microsoft rejected this Client ID\. (.*)$/, (m) =>
      `Microsoft отклонил этот Client ID. ${m[1]}`],
    [/^This Microsoft account needs to sign in again\.(.*)$/, (m) =>
      `Этому аккаунту Microsoft нужно войти снова.${m[1]}`],
    [/^This Ely\.by account needs to sign in again\.(.*)$/, (m) =>
      `Этому аккаунту Ely.by нужно войти снова.${m[1]}`],

    /* First-run setup: dynamic memory and recommendation lines */
    [/^(\d+) GB$/, (m) => `${m[1]} ГБ`],
    [/^(Recommended for this computer|Applied): (.+) GB RAM · (.+) chunks · (.+)\.$/, (m) => {
      const lead = m[1] === "Applied"
        ? "Применено" : "Рекомендация для этого компьютера";
      const tail = m[4]
        .replace("unlimited FPS", "без ограничения FPS")
        .replace("(light)", "(лёгкий)")
        .replace("(balanced)", "(сбалансированный)")
        .replace("(quality)", "(качественный)");
      return `${lead}: ${m[2]} ГБ ОЗУ · ${m[3]} чанков · ${tail}.`;
    }],
    [/^This computer has (.+) GB of RAM\. Leave room for Windows: (.+) GB is a good choice\.$/, (m) =>
      `На этом компьютере ${m[1]} ГБ ОЗУ. Оставьте память для Windows: ${m[2]} ГБ — хороший выбор.`],
  ];

  const normalize = (value) => String(value).replace(/\s+/g, " ").trim();

  function translate(raw) {
    const text = normalize(raw);
    if (!text) return null;
    if (Object.prototype.hasOwnProperty.call(RU, text)) return RU[text];
    for (const [pattern, replacement] of RULES) {
      if (pattern.test(text)) {
        const match = text.match(pattern);
        return typeof replacement === "function"
          ? replacement(match) : text.replace(pattern, replacement);
      }
    }
    return null;
  }

  function withEdges(original, translated) {
    const lead = (original.match(/^\s*/) || [""])[0];
    const trail = (original.match(/\s*$/) || [""])[0];
    return lead + translated + trail;
  }

  let lang = "en";
  const englishText = new WeakMap();
  const englishAttrs = new WeakMap();

  const skipped = (node) => {
    const element = node && (node.nodeType === 1 ? node : node.parentElement);
    if (!element) return true;
    return !!(element.closest
      && element.closest("[data-i18n-skip], script, style, noscript, textarea"));
  };

  function applyTextNode(node) {
    if (lang !== "ru" || skipped(node)) return;
    const original = node.nodeValue;
    if (!original || !original.trim()) return;
    const translated = translate(original);
    if (translated === null || translated === normalize(original)) {
      /* The app replaced a translated node with something we do not know
         (a user name, a path): drop the stale English copy so restoring the
         language never puts old text back. */
      const stored = englishText.get(node);
      if (stored !== undefined && original !== stored) {
        const roundTrip = translate(stored);
        const isOurTranslation = roundTrip !== null
          && normalize(original) === normalize(roundTrip);
        if (!isOurTranslation) englishText.delete(node);
      }
      return;
    }
    englishText.set(node, original);
    node.nodeValue = withEdges(original, translated);
  }

  function applyAttribute(element, name) {
    if (lang !== "ru" || skipped(element)) return;
    const value = element.getAttribute(name);
    if (!value) return;
    let stored = englishAttrs.get(element);
    const translated = translate(value);
    if (translated === null || translated === normalize(value)) {
      const previous = stored && stored[name];
      if (previous !== undefined && value !== previous) {
        const roundTrip = translate(previous);
        const isOurTranslation = roundTrip !== null
          && normalize(value) === normalize(roundTrip);
        if (!isOurTranslation) delete stored[name];
      }
      return;
    }
    if (!stored) {
      stored = Object.create(null);
      englishAttrs.set(element, stored);
    }
    stored[name] = value;
    element.setAttribute(name, translated);
  }

  function translateNode(root) {
    if (!root || lang !== "ru") return;
    if (root.nodeType === 3) {
      applyTextNode(root);
      return;
    }
    if (root.nodeType !== 1 && root.nodeType !== 9 && root.nodeType !== 11) {
      return;
    }
    if (root.nodeType === 1) {
      for (const name of ATTRS) applyAttribute(root, name);
    }
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node = walker.nextNode();
    while (node) {
      applyTextNode(node);
      node = walker.nextNode();
    }
    const elements = root.querySelectorAll
      ? root.querySelectorAll("*") : [];
    for (const element of elements) {
      for (const name of ATTRS) applyAttribute(element, name);
    }
  }

  function restore() {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node = walker.nextNode();
    while (node) {
      const stored = englishText.get(node);
      if (stored !== undefined) {
        const translated = translate(stored);
        const isUntouched = node.nodeValue === stored
          || (translated !== null
            && normalize(node.nodeValue) === normalize(translated));
        if (isUntouched) node.nodeValue = stored;
      }
      node = walker.nextNode();
    }
    for (const element of document.body.querySelectorAll("*")) {
      const stored = englishAttrs.get(element);
      if (!stored) continue;
      for (const name of ATTRS) {
        const english = stored[name];
        if (english === undefined) continue;
        const current = element.getAttribute(name);
        const translated = translate(english);
        const isUntouched = current === english
          || (translated !== null
            && normalize(current || "") === normalize(translated));
        if (isUntouched) element.setAttribute(name, english);
      }
    }
  }

  const observer = new MutationObserver((records) => {
    if (lang !== "ru") return;
    for (const record of records) {
      if (record.type === "characterData") {
        applyTextNode(record.target);
      } else if (record.type === "attributes") {
        applyAttribute(record.target, record.attributeName);
      } else {
        for (const added of record.addedNodes) translateNode(added);
      }
    }
  });

  function start() {
    observer.observe(document.body, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
      attributeFilter: ATTRS,
    });
  }

  function setLanguage(next) {
    const target = next === "ru" ? "ru" : "en";
    if (target === lang) {
      if (target === "ru") translateNode(document.body);
      return;
    }
    if (target === "en") {
      lang = "en";
      document.documentElement.lang = "en";
      restore();
      return;
    }
    lang = "ru";
    document.documentElement.lang = "ru";
    translateNode(document.body);
  }

  if (document.body) start();
  else document.addEventListener("DOMContentLoaded", start, { once: true });

  window.I18n = {
    setLanguage,
    translate,
    get language() { return lang; },
  };
})();
