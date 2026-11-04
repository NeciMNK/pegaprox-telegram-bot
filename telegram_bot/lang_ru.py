# -*- coding: utf-8 -*-
"""Russian texts of the bot. The key is the English text as written in the code."""

RU = {
    # help, commands
    "<b>Proxmox management through PegaProx</b>\n\n"
    "The bot acts as your PegaProx user, with the same permissions.\n\n"
    "<b>How to connect</b>\n"
    "1. In PegaProx open \"My Profile → API Tokens\" and create a token.\n"
    "2. Send it here in a private chat: <code>/login pgx_...</code>\n"
    "   The bot deletes the message with the token right away.\n\n"
    "<b>Commands</b>\n"
    "/menu: main menu (clusters, nodes, VMs and containers)\n"
    "/find <i>text</i>: find a VM/CT by name or ID\n"
    "/users: PegaProx users and their roles\n"
    "/alerts: active alerts\n"
    "/notify on|off: push new alerts\n"
    "/lang en|ru: language of the bot\n"
    "/whoami: your role and permissions\n"
    "/api <i>METHOD /api/path [JSON]</i>: any PegaProx API call\n"
    "/logout: unlink the account\n":
    "<b>Управление Proxmox через PegaProx</b>\n\n"
    "Бот работает от имени вашего пользователя PegaProx и с теми же правами.\n\n"
    "<b>Как подключиться</b>\n"
    "1. В PegaProx откройте «Мой профиль → API-токены» и создайте токен.\n"
    "2. Пришлите его сюда в личном чате: <code>/login pgx_...</code>\n"
    "   Сообщение с токеном бот сразу удалит.\n\n"
    "<b>Команды</b>\n"
    "/menu: главное меню (кластеры, ноды, VM и контейнеры)\n"
    "/find <i>текст</i>: найти VM/CT по имени или номеру\n"
    "/users: пользователи PegaProx и их роли\n"
    "/alerts: активные оповещения\n"
    "/notify on|off: присылать новые оповещения\n"
    "/lang en|ru: язык бота\n"
    "/whoami: ваша роль и права\n"
    "/api <i>METHOD /api/путь [JSON]</i>: любой запрос к API PegaProx\n"
    "/logout: отвязать аккаунт\n",
    'Main menu': 'Главное меню',
    'Find a VM/CT': 'Найти VM/CT',
    'PegaProx users': 'Пользователи PegaProx',
    'Active alerts': 'Активные оповещения',
    'Notifications on/off': 'Уведомления вкл/выкл',
    'Language': 'Язык',
    'My permissions': 'Мои права',
    'Link an account': 'Подключить аккаунт',
    'Unlink the account': 'Отвязать аккаунт',
    'API request': 'Запрос к API',
    'Help': 'Справка',
    'Choose the language:': 'Выберите язык:',
    'Language: English': 'Язык: русский',

    # linking, access
    'Open /menu or see /help': 'Откройте /menu или посмотрите /help',
    'Unknown command. /help': 'Неизвестная команда. /help',
    'Link your PegaProx account first: /login <i>token</i>. More: /help':
        'Сначала подключите аккаунт PegaProx: /login <i>токен</i>. Подробнее: /help',
    '✅ Account linked. PegaProx role: <b>{role}</b>.\nNew alerts will be sent here (/notify off to stop).':
        '✅ Аккаунт подключён. Роль в PegaProx: <b>{role}</b>.\n'
        'Новые оповещения будут приходить сюда (/notify off, чтобы отключить).',
    'Account unlinked. The token itself still works: revoke it in PegaProx ("My Profile → API Tokens").':
        'Аккаунт отвязан. Сам токен продолжает работать: отзовите его в PegaProx («Мой профиль → API-токены»).',
    'Role: <b>{role}</b>\nTenant: {tenant}\nPermissions ({count}): <code>{perms}</code>':
        'Роль: <b>{role}</b>\nТенант: {tenant}\nПрава ({count}): <code>{perms}</code>',
    '❌ PegaProx rejected the token (revoked or expired). Link again: /login':
        '❌ PegaProx отклонил токен (отозван или истёк). Подключитесь заново: /login',
    'I deleted the message with the token': 'Сообщение с токеном я удалил',
    'I could not delete the message with the token': 'Удалить сообщение с токеном не получилось',
    '{warn}. Send tokens only in a private chat with the bot, and revoke this one in PegaProx.':
        '{warn}. Присылайте токены только в личном чате с ботом, а этот отзовите в PegaProx.',
    '{warn}; revoke that token in PegaProx.': '{warn}; отзовите этот токен в PegaProx.',
    'Access to this bot is closed. Your Telegram id: <code>{uid}</code>':
        'Доступ к этому боту закрыт. Ваш Telegram id: <code>{uid}</code>',
    'Send the token only in a private chat with the bot. If you sent it here, revoke the token in PegaProx.':
        'Присылайте токен только в личном чате с ботом. Если вы отправили его сюда, отзовите токен в PegaProx.',
    'Send a PegaProx API token: <code>/login pgx_...</code>\nYou can create one under "My Profile → API Tokens".':
        'Пришлите API-токен PegaProx: <code>/login pgx_...</code>\nСоздать его можно в «Мой профиль → API-токены».',
    '❌ PegaProx did not accept the token: it is wrong, revoked or expired.':
        '❌ PegaProx не принял токен: он неверный, отозван или истёк.',
    '❌ Could not check the token: {error}': '❌ Не удалось проверить токен: {error}',
    'Alert notifications are on.': 'Уведомления об оповещениях включены.',
    'Notifications are off.': 'Уведомления выключены.',
    'This button has expired, open /menu': 'Эта кнопка устарела, откройте /menu',
    'No account linked: /login': 'Аккаунт не подключён: /login',
    'User management works only in a private chat with the bot.':
        'Управление пользователями работает только в личном чате с ботом.',

    # /api
    'I deleted the message': 'Сообщение я удалил',
    'I could not delete the message (the bot needs admin rights here)':
        'Удалить сообщение не получилось (боту нужны права администратора в этом чате)',
    '/api works only in a private chat with the bot. {done}; if it held a password, change it.':
        '/api работает только в личном чате с ботом. {done}; если там был пароль, смените его.',
    'Usage: <code>/api GET /api/clusters</code>\nor <code>/api POST /api/path {"key": "value"}</code>':
        'Формат: <code>/api GET /api/clusters</code>\nили <code>/api POST /api/путь {"key": "value"}</code>',
    'The request body must be JSON.': 'Тело запроса должно быть в формате JSON.',

    # errors, results
    '⛔ Permission denied: {error}': '⛔ Нет прав: {error}',
    '❌ Error: {error}': '❌ Ошибка: {error}',
    'Task: <code>{task}</code>': 'Задача: <code>{task}</code>',

    # clusters, nodes
    '<b>Clusters</b>': '<b>Кластеры</b>',
    'No clusters available.': 'Нет доступных кластеров.',
    'Nodes: {online} of {total} online': 'Ноды: {online} из {total} онлайн',
    'Nodes: {error}': 'Ноды: {error}',
    'Guests: {running} of {total} running': 'Гости: {running} из {total} запущены',
    '🔔 Alerts': '🔔 Оповещения',
    '🔍 Search': '🔍 Поиск',
    '👥 Users': '👥 Пользователи',
    '« Clusters': '« Кластеры',
    '🖥 Nodes': '🖥 Ноды',
    '📦 VMs and CTs': '📦 VM и CT',
    '📋 Tasks': '📋 Задачи',
    '🛡 Firewall': '🛡 Файрвол',
    '💽 Storage': '💽 Хранилища',
    '🔄 Refresh': '🔄 Обновить',
    '« Back': '« Назад',
    '« Nodes': '« Ноды',
    '« List': '« Список',
    'Cancel': 'Отмена',
    '<b>{cluster}: nodes</b>': '<b>{cluster}: ноды</b>',
    '🔄 Reboot': '🔄 Перезагрузка',
    '⏻ Shutdown': '⏻ Выключение',
    'PegaProx allows reboot and shutdown only for a node in maintenance mode.':
        'PegaProx разрешает перезагрузку и выключение только для ноды в режиме обслуживания.',
    'Reboot node <b>{node}</b>?': 'Перезагрузить ноду <b>{node}</b>?',
    'Shut down node <b>{node}</b>?': 'Выключить ноду <b>{node}</b>?',
    '✅ Yes, reboot': '✅ Да, перезагрузить',
    '✅ Yes, shut down': '✅ Да, выключить',
    'Node {node}: reboot started': 'Нода {node}: перезагрузка запущена',
    'Node {node}: shutdown started': 'Нода {node}: выключение запущено',

    # guests
    '<b>{cluster}: VMs and containers</b> ({count}), page {page}/{pages}':
        '<b>{cluster}: VM и контейнеры</b> ({count}), страница {page}/{pages}',
    'Guest {vmid} not found.': 'Гость {vmid} не найден.',
    '▶️ Start': '▶️ Запустить',
    'Start': 'Запуск',
    'Shutdown': 'Выключение',
    'Reboot': 'Перезагрузка',
    '⏹ Stop (hard)': '⏹ Стоп (жёстко)',
    'Hard stop': 'Жёсткая остановка',
    '⚡ Reset': '⚡ Сброс',
    'Reset': 'Сброс',
    '⏸ Suspend': '⏸ Пауза',
    'Suspend': 'Пауза',
    '⏯ Resume': '⏯ Продолжить',
    'Resume': 'Продолжение',
    '✅ Yes: {action}': '✅ Да: {action}',
    '✅ Yes': '✅ Да',
    '📸 Snapshots': '📸 Снапшоты',
    '💾 Backups': '💾 Бэкапы',
    '🚚 Migrate': '🚚 Миграция',
    'Type a VM/CT name or ID:': 'Введите имя или номер VM/CT:',
    'Found: {count}': 'Найдено: {count}',
    'Nothing found for "{query}".': 'По запросу «{query}» ничего не найдено.',

    # snapshots
    '<b>Snapshots of {name} ({vmid})</b>': '<b>Снапшоты {name} ({vmid})</b>',
    'No snapshots': 'Снапшотов нет',
    '➕ Create': '➕ Создать',
    '↩️ Roll back': '↩️ Откатить',
    '🗑 Delete': '🗑 Удалить',
    '« Snapshots': '« Снапшоты',
    'Snapshot <b>{snap}</b> of {name} ({vmid})': 'Снапшот <b>{snap}</b> гостя {name} ({vmid})',
    'Roll back to snapshot <b>{snap}</b>?': 'Откатиться к снапшоту <b>{snap}</b>?',
    'The current state of the guest will be lost.': 'Текущее состояние гостя будет потеряно.',
    'Delete snapshot <b>{snap}</b>?': 'Удалить снапшот <b>{snap}</b>?',
    'Rollback to snapshot {snap}': 'Откат к снапшоту {snap}',
    'Deleting snapshot {snap}': 'Удаление снапшота {snap}',
    'Create "{name}"': 'Создать «{name}»',
    'Type a name for the new snapshot or press the button:': 'Введите имя нового снапшота или нажмите кнопку:',
    'Creating snapshot <b>{name}</b>': 'Создаётся снапшот <b>{name}</b>',
    'Snapshot name: Latin letters, digits, _ and -, starting with a letter. Try again:':
        'Имя снапшота: латинские буквы, цифры, _ и -, начинается с буквы. Попробуйте ещё раз:',

    # backups, migration
    '<b>Backups of {name} ({vmid})</b>': '<b>Бэкапы {name} ({vmid})</b>',
    'No backups': 'Бэкапов нет',
    '➕ Back up now': '➕ Сделать бэкап',
    'No backup storage available on this node.': 'На этой ноде нет хранилища для бэкапов.',
    'Where to store the backup (snapshot mode, zstd)?': 'Куда сохранить бэкап (режим snapshot, zstd)?',
    'Backup of {name} to {storage} started': 'Бэкап {name} в {storage} запущен',
    'No other online node to migrate to.': 'Нет другой ноды онлайн для миграции.',
    'Migrate <b>{name}</b> from {node} to:': 'Мигрировать <b>{name}</b> с {node} на:',
    'Migrate <b>{name}</b> ({vmid}) to <b>{target}</b>?': 'Мигрировать <b>{name}</b> ({vmid}) на <b>{target}</b>?',
    '✅ Migrate': '✅ Мигрировать',
    'Migration of {name} to {target} started': 'Миграция {name} на {target} запущена',

    # firewall
    '<b>Datacenter firewall of {cluster}</b>': '<b>Файрвол датацентра {cluster}</b>',
    'State: {state}': 'Состояние: {state}',
    '✅ enabled': '✅ включён',
    '⛔ disabled': '⛔ выключен',
    'Policy in: {pin}, out: {pout}': 'Политика входящих: {pin}, исходящих: {pout}',
    'No rules': 'Правил нет',
    '⛔ Disable firewall': '⛔ Выключить файрвол',
    '✅ Enable firewall': '✅ Включить файрвол',
    'The #N buttons turn a rule on or off.': 'Кнопки #N включают и выключают правило.',
    'Enable the datacenter firewall?': 'Включить файрвол датацентра?',
    'Disable the datacenter firewall?': 'Выключить файрвол датацентра?',
    'Make sure there are rules that allow the web UI and SSH, or you may lock yourself out.':
        'Проверьте, что есть правила, разрешающие веб-интерфейс и SSH, иначе можно потерять доступ.',
    'Firewall enabled': 'Файрвол включён',
    'Firewall disabled': 'Файрвол выключен',
    '<b>Firewall {name} ({vmid})</b>': '<b>Файрвол {name} ({vmid})</b>',
    '⚠️ The rules changed since that list was drawn, nothing was toggled. Here is the current list.\n\n':
        '⚠️ Правила изменились после того, как был показан список, ничего не переключено. Вот текущий список.\n\n',

    # storage, tasks, alerts
    '<b>Storage of {cluster}</b>': '<b>Хранилища {cluster}</b>',
    '<b>Latest tasks of {cluster}</b>': '<b>Последние задачи {cluster}</b>',
    'No tasks': 'Задач нет',
    '<b>Alerts of {cluster}</b>': '<b>Оповещения {cluster}</b>',
    '<b>Active alerts</b>': '<b>Активные оповещения</b>',
    'No active alerts ✅': 'Активных оповещений нет ✅',
    '✔️ Acknowledge #{id}': '✔️ Подтвердить #{id}',
    '✔️ Acknowledge': '✔️ Подтвердить',
    '✔️ Alert #{id} acknowledged': '✔️ Оповещение #{id} подтверждено',

    # PegaProx users
    'Managing PegaProx users needs the admin.users permission (usually the admin role), '
    'and the token linked to the bot needs that role too.':
        'Для управления пользователями PegaProx нужно право admin.users (обычно роль admin), '
        'и токен, привязанный к боту, тоже должен иметь эту роль.',
    '<b>PegaProx users</b> ({count}), page {page}/{pages}\n🟢 enabled, ⚪ disabled':
        '<b>Пользователи PegaProx</b> ({count}), страница {page}/{pages}\n🟢 включён, ⚪ выключен',
    'User {name} not found.': 'Пользователь {name} не найден.',
    'Role: <b>{role}</b>, tenant: {tenant}': 'Роль: <b>{role}</b>, тенант: {tenant}',
    '🟢 enabled': '🟢 включён',
    '⚪ disabled': '⚪ выключен',
    'Login: {source}, 2FA: {tfa}': 'Вход: {source}, 2FA: {tfa}',
    'yes': 'да',
    'no': 'нет',
    'Last login: {time}': 'Последний вход: {time}',
    'never': 'никогда',
    'Extra permissions: <code>{perms}</code>': 'Дополнительные права: <code>{perms}</code>',
    '⚪ Disable': '⚪ Выключить',
    '🟢 Enable': '🟢 Включить',
    '🎭 Role': '🎭 Роль',
    '🔐 Password': '🔐 Пароль',
    '🔓 Reset 2FA': '🔓 Сбросить 2FA',
    '« Users': '« Пользователи',
    '✅ Yes, disable': '✅ Да, выключить',
    'Disable <b>{name}</b>? They will not be able to log in to PegaProx or use the bot.':
        'Выключить <b>{name}</b>? Пользователь не сможет войти в PegaProx и пользоваться ботом.',
    'New role for <b>{name}</b>:\nadmin: everything, user: manage guests, viewer: read only.':
        'Новая роль для <b>{name}</b>:\nadmin: всё, user: управление гостями, viewer: только просмотр.',
    "Send the new password for <b>{name}</b>.\nPrivate chat only: I delete the message with the password "
    "right away. All of the user's sessions will be closed.":
        'Пришлите новый пароль для <b>{name}</b>.\nТолько в личном чате: сообщение с паролем я сразу удалю. '
        'Все сессии пользователя будут закрыты.',
    '✅ Yes, reset': '✅ Да, сбросить',
    'Reset two-factor authentication for <b>{name}</b>? '
    'They will log in with the password only until they set it up again.':
        'Сбросить двухфакторную аутентификацию для <b>{name}</b>? '
        'Пользователь будет входить только по паролю, пока не настроит её заново.',
    '2FA of {name} reset': '2FA пользователя {name} сброшена',
    '✅ Yes, delete': '✅ Да, удалить',
    'Delete PegaProx user <b>{name}</b>? Their API tokens stop working too. This cannot be undone.':
        'Удалить пользователя PegaProx <b>{name}</b>? Его API-токены тоже перестанут работать. Это нельзя отменить.',
    'User {name} deleted': 'Пользователь {name} удалён',
    '<b>New PegaProx user</b>\nSend the username (Latin letters, digits, dot, -, _; at least 3 characters):':
        '<b>Новый пользователь PegaProx</b>\nПришлите имя пользователя (латинские буквы, цифры, точка, -, _; '
        'не меньше 3 символов):',
    'Password for <b>{name}</b> (role {role}).\nBy default PegaProx requires 8+ characters with an upper case '
    'letter, a lower case letter and a digit. I delete the message with the password right away.':
        'Пароль для <b>{name}</b> (роль {role}).\nПо умолчанию PegaProx требует не меньше 8 символов, '
        'заглавную и строчную букву и цифру. Сообщение с паролем я сразу удалю.',
    'Username: Latin letters, digits, dot, - and _, 3 to 64 characters. Try again:':
        'Имя пользователя: латинские буквы, цифры, точка, - и _, от 3 до 64 символов. Попробуйте ещё раз:',
    'Which role should <b>{name}</b> have?': 'Какую роль дать <b>{name}</b>?',
    'Send passwords only in a private chat with the bot. If you sent it here, change it.':
        'Присылайте пароли только в личном чате с ботом. Если вы отправили его сюда, смените его.',
    'Send another password:': 'Пришлите другой пароль:',
    '✅ PegaProx user <b>{name}</b> created.': '✅ Пользователь PegaProx <b>{name}</b> создан.',
    '✅ Password of {name} changed.': '✅ Пароль {name} изменён.',

    # views
    '{d}d {h}h': '{d} д {h} ч',
    '{h}h {m}m': '{h} ч {m} мин',
    '{used} of {total}': '{used} из {total}',
    '🖥 Node <b>{node}</b>': '🖥 Нода <b>{node}</b>',
    'Status: {status}': 'Статус: {status}',
    'CPU: {pct} of {cores} cores': 'CPU: {pct} из {cores} ядер',
    'Disk: {used} of {total}': 'Диск: {used} из {total}',
    'Uptime: {time}': 'Аптайм: {time}',
    '🛠 In maintenance': '🛠 На обслуживании',
    'Cluster: {cluster}\nNode: {node}\nState: {state}': 'Кластер: {cluster}\nНода: {node}\nСостояние: {state}',
    'on {node}': 'на {node}',
    'Alert': 'Оповещение',
    'Cluster: {cluster}': 'Кластер: {cluster}',
    'Target: {target}': 'Объект: {target}',
    '(threshold {op} {value})': '(порог {op} {value})',
    'Since {time}': 'С {time}',
    'Acknowledged by: {user}': 'Подтвердил: {user}',
    'from {addr}': 'от {addr}',
    'to {addr}': 'к {addr}',
    'port {port}': 'порт {port}',
}
