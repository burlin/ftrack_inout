# ftrack_inout

Плагин для ftrack Connect: браузер ассетов, паблиш, интеграция с DCC (Houdini, Maya и др.).

## Установка зависимостей

Зависимости должны находиться в папке **`dependencies/`** рядом с кодом (плагин добавляет её в `sys.path`).

Из корня репозитория:

```bash
pip install -r requirements.txt -t dependencies
```

Подробности и варианты — в [requirements.txt](requirements.txt).

## Структура

- **browser/** — браузер ассетов, перенос файлов, DCC-интеграция
- **common/** — сессия ftrack, кэш, общие утилиты
- **publisher/** — паблиш версий и компонентов
- **ftrack_hou_utils/** — утилиты для Houdini

Папка `dependencies/` в репозиторий не входит (см. `.gitignore`); её создаёт пользователь командой выше.
