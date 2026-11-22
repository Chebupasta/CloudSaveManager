"""
Модели данных: игра (GameProfile), слот сохранения (SaveSlot),
облачный аккаунт (CloudAccount).

Все модели умеют сериализоваться в dict/JSON и обратно, поэтому
их удобно хранить в конфигурационных файлах.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any


def new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class SaveSlot:
    id: str = field(default_factory=new_id)
    label: str = 'Сохранение'
    # Абсолютный путь к файлу или папке сохранения на диске.
    path: str = ''
    # True, если path указывает на папку (тогда при выгрузке она
    # упаковывается в zip, а при загрузке распаковывается обратно).
    is_directory: bool = False
    # Имя, под которым сохранение будет храниться в облаке.
    remote_name: str = 'save.dat'
    # Ключ автоопределения пути для встроенных пресетов (например 'ds3_orig').
    # Для пользовательских игр не используется.
    detect_key: Optional[str] = None
    last_upload: Optional[str] = None
    last_download: Optional[str] = None
    # Отпечаток (хэш) содержимого на момент последней успешной синхронизации.
    # Нужен, чтобы понять, что изменилось: локальный файл или облако.
    synced_fingerprint: Optional[str] = None
    # Маски файлов, которые НЕ выгружаются из папки (через запятую), например:
    # '*.log, cache, screenshots/*'. Совпадающие локальные файлы при загрузке не трогаются.
    exclude_patterns: str = ''

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'SaveSlot':
        slot = SaveSlot()
        slot.__dict__.update({k: v for k, v in data.items() if k in slot.__dict__})
        return slot


@dataclass
class GameProfile:
    id: str = field(default_factory=new_id)
    name: str = 'Новая игра'
    preset_key: Optional[str] = None
    # Имена исполняемых файлов игры (для отслеживания процесса), например
    # ['DarkSoulsIII.exe']. Сравнение регистронезависимое.
    process_names: List[str] = field(default_factory=list)
    # Автоматически выгружать сохранение в облако после закрытия игры.
    auto_upload_on_exit: bool = True
    # Необязательная страховка на случай вылета/отключения питания: каждые N минут
    # игры выгружать сохранение, не дожидаясь её закрытия (0 — выключено).
    periodic_upload_minutes: int = 0
    # Что запускать кнопкой «Играть»: путь к .exe или ссылка вроде steam://rungameid/374320.
    launch_command: str = ''
    # Автоснимки во время игры: раз в N минут (0 — выключено), хранятся последние 10.
    snapshot_minutes: int = 0
    # Статистика: суммарное время в игре, последний запуск и число запусков.
    playtime_seconds: int = 0
    last_played: str = ''
    launch_count: int = 0
    # При запуске игры проверять облако и предлагать скачать более новое сохранение.
    check_cloud_on_start: bool = True
    # Путь к exe, найденный при добавлении игры (подсказка для повторного поиска).
    hint_exe_path: str = ''
    # ID облачного аккаунта (CloudAccount.id), который используется для этой игры.
    account_id: Optional[str] = None
    # Префикс пути в облаке (папка), под которым хранятся сохранения игры.
    remote_prefix: str = ''
    # Путь к локальной картинке-иконке игры (Steam-арт, иконка из .exe или
    # выбранная пользователем). Пусто — используется векторная иконка по умолчанию.
    icon_path: str = ''
    slots: List[SaveSlot] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['slots'] = [s.to_dict() for s in self.slots]
        return d

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'GameProfile':
        game = GameProfile()
        for k, v in data.items():
            if k == 'slots':
                continue
            if k in game.__dict__:
                setattr(game, k, v)
        game.slots = [SaveSlot.from_dict(s) for s in data.get('slots', [])]
        return game


@dataclass
class AppSettings:
    # Сворачивать окно в трей при нажатии на крестик вместо закрытия программы.
    minimize_to_tray: bool = True
    # Запускать программу сразу свёрнутой в трей (используется вместе с автозапуском).
    start_minimized: bool = False
    # Показывать уведомление трея при автоматической выгрузке/находке новой версии.
    tray_notifications: bool = True
    # Временно приостановить отслеживание всех процессов (без удаления игр).
    monitoring_paused: bool = False
    # Спрашивать подтверждение перед быстрой загрузкой из трея (по умолчанию
    # выключено — скорость важнее, а резервная копия создаётся всё равно).
    confirm_tray_download: bool = False
    # --- игровые функции ---
    play_lock_enabled: bool = True      # отметка «играют на …» в облаке (защита от игры на двух ПК)
    sort_recent: bool = False           # список игр: сначала недавно запущенные
    # --- обновления из GitHub Releases ---
    check_updates: bool = True          # проверять новую версию при запуске
    update_repo: str = ''               # репозиторий GitHub в формате owner/repo
    # --- вид и ресурсы ---
    theme: str = 'glass'                # оформление: 'glass' (по умолчанию), 'glass_dark', 'light' или 'dark'; применяется при запуске
    animations: bool = True             # короткие плавные анимации интерфейса
    eco_mode_in_tray: bool = True       # когда окно скрыто: режим эффективности + сброс памяти
    # --- тонкая настройка ---
    poll_interval_sec: int = 5          # как часто проверять процессы игр
    exit_confirm_polls: int = 2         # сколько проверок подряд без процесса = игра закрыта
    exit_upload_delay_sec: int = 4      # пауза после закрытия игры перед выгрузкой
    periodic_stable_sec: int = 20       # файл должен не меняться столько секунд (выгрузка во время игры)
    max_backups_per_slot: int = 5       # локальных резервных копий на слот
    max_auto_snapshot_mb: int = 300     # автоснимки не делаются для слотов больше (МБ); 0 — без ограничения
    retry_failed_uploads: bool = True   # повторять неудачную автовыгрузку (30 с, 2, 10, 30 мин)
    # --- каталог игр в облаке (второй компьютер подхватывает игры первого) ---
    catalog_sync: bool = True           # публиковать список игр в облако и подхватывать чужие
    auto_download_imported: bool = True # сразу скачивать сохранения подхваченных игр, если локально их нет
    ignored_catalog: List[str] = field(default_factory=list)  # 'аккаунт:игра' — удалённые вручную, не добавлять снова

    def clamp(self) -> 'AppSettings':
        def lim(v, lo, hi, default):
            try:
                return max(lo, min(hi, int(v)))
            except (TypeError, ValueError):
                return default
        self.poll_interval_sec = lim(self.poll_interval_sec, 2, 60, 5)
        self.exit_confirm_polls = lim(self.exit_confirm_polls, 1, 10, 2)
        self.exit_upload_delay_sec = lim(self.exit_upload_delay_sec, 0, 60, 4)
        self.periodic_stable_sec = lim(self.periodic_stable_sec, 5, 300, 20)
        self.max_backups_per_slot = lim(self.max_backups_per_slot, 1, 100, 5)
        self.max_auto_snapshot_mb = lim(self.max_auto_snapshot_mb, 0, 100000, 300)
        if self.theme not in ('glass', 'glass_dark', 'light', 'dark'):
            self.theme = 'glass'
        if not isinstance(self.ignored_catalog, list):
            self.ignored_catalog = []
        return self

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'AppSettings':
        settings = AppSettings()
        for k, v in (data or {}).items():
            if k in settings.__dict__:
                setattr(settings, k, v)
        return settings.clamp()


@dataclass
class CloudAccount:
    id: str = field(default_factory=new_id)
    # Тип провайдера: 'github', 'gitlab', 'webdav', 'local'
    type: str = 'github'
    name: str = 'Аккаунт'
    # Нечувствительные настройки (url репозитория, папка и т.д.)
    config: Dict[str, Any] = field(default_factory=dict)
    # Чувствительные данные (токены/пароли) хранятся отдельно через
    # secrets_store и НЕ попадают в этот словарь при сохранении на диск.
    # Однако в рантайме они могут временно лежать здесь же, под ключом
    # secret, для удобства передачи в провайдер.
    secret: str = field(default='', repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'type': self.type,
            'name': self.name,
            'config': self.config,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'CloudAccount':
        acc = CloudAccount()
        acc.id = data.get('id', acc.id)
        acc.type = data.get('type', acc.type)
        acc.name = data.get('name', acc.name)
        acc.config = data.get('config', {}) or {}
        return acc
