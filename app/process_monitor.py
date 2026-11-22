"""
Фоновый поток, который отслеживает запущенные процессы игр:
  - при старте игры (если включена проверка) сверяет локальное сохранение
    с облаком и сообщает, если в облаке есть более новая версия или
    произошёл конфликт (сохранение менялось в двух местах);
  - при закрытии игры автоматически выгружает сохранение в облако (если
    это не отключено для игры).

Работает через опрос списка процессов (psutil) с небольшим интервалом —
это гораздо безопаснее для GitHub/GitLab, чем старое автосохранение по
таймеру, так как выгрузка происходит один раз за сессию игры.
"""
import os
import threading
import time

from PyQt5.QtCore import QThread, pyqtSignal

from app import backup, sync_manager
from app.constants import RETRY_DELAYS, RUNTIME
from app.logger import log_action
from app.store import ConfigStore

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None


class ProcessMonitor(QThread):
    game_started = pyqtSignal(str)   # game_id
    game_exited = pyqtSignal(str)    # game_id, сохранение уже выгружено (или предпринята попытка)
    upload_result = pyqtSignal(str, list)  # game_id, [(slot_id, ok, message), ...]
    sync_check_result = pyqtSignal(str, str, dict)  # game_id, slot_id, status_dict
    play_conflict = pyqtSignal(str, str, str)  # game_id, устройство, с какого времени — игру уже запустили на другом ПК
    periodic_result = pyqtSignal(str, list)  # game_id, [(slot_id, ok, message)] — выгрузка во время игры
    status_changed = pyqtSignal(str)  # текст для статус-бара

    def __init__(self, store: ConfigStore, parent=None):
        super().__init__(parent)
        self.store = store
        self._state_lock = threading.Lock()  # _running_state читает и GUI-поток
        self._running_state = {}  # game_id -> bool
        self._pending_upload = {}  # game_id -> время, когда пора выгрузить после выхода игры
        self._missing_polls = {}  # game_id -> сколько опросов подряд процесса не видно
        self._stop_requested = False
        self._wake = threading.Event()    # будит поток при остановке — без периодических пробуждений
        self._name_cache = {}             # pid -> (create_time, имя процесса)
        self._last_status = ''
        self._started_at = {}       # game_id -> время старта сессии (для учёта времени в игре)
        self._last_heartbeat = {}   # game_id -> когда обновляли отметку «играют»
        self._last_snapshot = {}    # game_id -> время последнего автоснимка
        self._snap_fp = {}          # (game_id, slot_id) -> отпечаток последнего автоснимка
        self._snap_sig = {}         # (game_id, slot_id) -> stat-подпись при последней проверке
        self._snap_too_big = set()  # слоты, пропущенные из-за лимита размера (лог пишется один раз)
        self._last_periodic = {}  # game_id -> время последней периодической выгрузки
        self._retries = {}  # game_id -> {'attempt': n, 'due': timestamp}: повтор неудачной автовыгрузки

    def stop(self):
        self._stop_requested = True
        self.requestInterruption()
        self._wake.set()

    def poll_now(self):
        """Внеочередная проверка (например, после смены настроек)."""
        self._wake.set()

    def is_any_game_running(self) -> bool:
        """Потокобезопасная проверка для GUI (иначе итерация по dict, который
        одновременно меняет поток монитора, падает с RuntimeError)."""
        with self._state_lock:
            return any(self._running_state.values())

    def _was_running(self, game_id: str) -> bool:
        with self._state_lock:
            return self._running_state.get(game_id, False)

    def _set_running(self, game_id: str, value: bool):
        with self._state_lock:
            self._running_state[game_id] = value

    def _process_pending_uploads(self):
        """Отложенная выгрузка после закрытия игры — вместо time.sleep() в цикле
        опроса, который замораживал слежение за всеми остальными играми."""
        now = time.time()
        for game_id, due in list(self._pending_upload.items()):
            if due > now:
                continue
            self._pending_upload.pop(game_id, None)
            game = self.store.get_game(game_id)
            if game and game.auto_upload_on_exit and not self._was_running(game_id):
                self._auto_upload_after_exit(game)

    def _emit_status(self, text: str):
        if text != self._last_status:  # не тревожим интерфейс одинаковыми сообщениями
            self._last_status = text
            self.status_changed.emit(text)

    def run(self):
        log_action('process_monitor', 'start')
        while not self._stop_requested and not self.isInterruptionRequested():
            try:
                self._poll_once()
            except Exception as e:  # монитор не должен падать из-за единичной ошибки
                log_action('process_monitor', 'error', str(e))
            # одно ожидание вместо цикла по 0,5 с: поток спит до следующей проверки
            self._wake.wait(int(self.store.settings.poll_interval_sec))
            self._wake.clear()
        log_action('process_monitor', 'stop')

    def _current_process_names(self):
        """Возвращает множество имён запущенных процессов (в нижнем регистре).
        Имя берём и из name, и из имени exe-файла: у некоторых защищённых
        процессов (античит и т.п.) name может прийти пустым."""
        names = set()
        if psutil is None:
            return names
        cache, seen = self._name_cache, set()
        for proc in psutil.process_iter():  # объекты процессов переиспользуются между вызовами
            try:
                pid = proc.pid
                created = proc.create_time()  # psutil кэширует; защита от повторного использования PID
                hit = cache.get(pid)
                if hit and hit[0] == created:
                    name = hit[1]
                else:
                    name = proc.name() or os.path.basename(proc.exe() or '')
                    cache[pid] = (created, name)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            seen.add(pid)
            if name:
                names.add(name.lower())
        for pid in [p for p in cache if p not in seen]:  # завершившиеся процессы
            del cache[pid]
        return names

    @staticmethod
    def _is_running(wanted: set, proc_names: set) -> bool:
        if wanted & proc_names:
            return True
        # Linux/Proton: comm обрезается до 15 символов ('darksoulsiii.ex')
        return any(len(p) >= 15 and any(w.startswith(p) for w in wanted) for p in proc_names
                   if len(p) == 15)

    def _poll_once(self):
        if self.store.settings.monitoring_paused:
            # Намеренно не трогаем self._running_state, пока на паузе: если
            # игра была (или будет) запущена в это время, при возобновлении
            # слежения не возникнет ложного срабатывания "игра запущена"
            # или "игра закрыта" из-за пропущенного перехода.
            self._emit_status('Отслеживание процессов приостановлено')
            return

        self._process_retries()
        self._process_pending_uploads()

        with self.store._lock:
            games = [g for g in self.store.games if g.process_names]
        if not games:
            self._emit_status('Отслеживание процессов: нет игр с указанным .exe')
            return

        proc_names = self._current_process_names()
        running_titles = []

        for game in games:
            wanted = {p.lower() for p in game.process_names if p}
            is_running = self._is_running(wanted, proc_names)
            was_running = self._was_running(game.id)

            if is_running:
                self._missing_polls[game.id] = 0
                running_titles.append(game.name)
                if was_running:
                    self._maybe_periodic_upload(game)
                    self._maybe_snapshot(game)
                    self._heartbeat(game)
                if not was_running:
                    self._last_periodic[game.id] = time.time()
                    self._started_at[game.id] = time.time()
                    self._last_snapshot[game.id] = time.time()
                    self._on_session_start(game)
                    self._pending_upload.pop(game.id, None)  # игра запустилась снова — выгрузку отменяем
                    self._set_running(game.id, True)
                    self.game_started.emit(game.id)
                    log_action('process_monitor', 'game_started', game.name)
                    # При запуске НИЧЕГО не выгружаем — только сверяем с облаком
                    # и предупреждаем, чтобы более новое облачное сохранение
                    # не было затёрто локальным.
                    if game.check_cloud_on_start and game.account_id:
                        self._check_cloud_on_start(game)
            elif was_running:
                # Игра могла "мигнуть" (перезапуск лаунчера, смена процесса) —
                # считаем её закрытой только после двух опросов подряд.
                missing = self._missing_polls.get(game.id, 0) + 1
                self._missing_polls[game.id] = missing
                if missing < self.store.settings.exit_confirm_polls:
                    running_titles.append(game.name)
                    continue
                self._set_running(game.id, False)
                self._last_periodic.pop(game.id, None)
                self._on_session_end(game)
                self._missing_polls[game.id] = 0
                log_action('process_monitor', 'game_exited', game.name)
                self.game_exited.emit(game.id)
                if game.auto_upload_on_exit:
                    # Игра успеет дописать файл на диск, но поток продолжает
                    # опрашивать остальные игры — выгрузка идёт на следующем опросе.
                    delay = int(self.store.settings.exit_upload_delay_sec)
                    if delay > 0:
                        self._pending_upload[game.id] = time.time() + delay
                    else:
                        self._auto_upload_after_exit(game)
                else:
                    log_action('process_monitor', 'auto_upload_disabled', game.name)

        if running_titles:
            self._emit_status('Сейчас запущено: ' + ', '.join(running_titles))
        else:
            self._emit_status(f'Отслеживание процессов: игры не запущены '
                                      f'({len(games)} под наблюдением)')

    def _check_cloud_on_start(self, game):
        for slot in game.slots:
            if not slot.path:
                continue
            try:
                status = sync_manager.check_slot_sync_status(self.store, game, slot)
            except Exception as e:
                status = {'status': 'error', 'message': str(e)}
            if status.get('status') in ('cloud_newer', 'conflict', 'error', 'empty_local'):
                self.sync_check_result.emit(game.id, slot.id, status)

    # ---------- статистика, отметка «играют», автоснимки ----------

    def _background(self, fn, *args):
        """Сетевые мелочи — в отдельном потоке-демоне, чтобы не тормозить опрос процессов."""
        threading.Thread(target=fn, args=args, daemon=True).start()

    def _on_session_start(self, game):
        fresh = self.store.get_game(game.id)
        if fresh:
            fresh.launch_count += 1
            fresh.last_played = time.strftime('%Y-%m-%dT%H:%M:%S')
            self.store.update_game(fresh)
        if self.store.settings.play_lock_enabled and game.account_id:
            self._last_heartbeat[game.id] = time.time()
            self._background(self._announce_playing, game)

    def _announce_playing(self, game):
        other = sync_manager.playing_elsewhere(self.store, game)
        if other:
            self.play_conflict.emit(game.id, other['device'], other['since'])
        sync_manager.set_playing(self.store, game, True)

    def _heartbeat(self, game):
        if not (self.store.settings.play_lock_enabled and game.account_id):
            return
        now = time.time()
        if now - self._last_heartbeat.get(game.id, now) >= sync_manager.PLAY_HEARTBEAT_SECONDS:
            self._last_heartbeat[game.id] = now
            self._background(sync_manager.set_playing, self.store, game, True)

    def _on_session_end(self, game):
        started = self._started_at.pop(game.id, None)
        fresh = self.store.get_game(game.id)
        if fresh and started:
            fresh.playtime_seconds += max(0, int(time.time() - started))
            self.store.update_game(fresh)
        self._last_heartbeat.pop(game.id, None)
        self._last_snapshot.pop(game.id, None)
        if self.store.settings.play_lock_enabled and game.account_id:
            self._background(sync_manager.set_playing, self.store, game, False)

    def _maybe_snapshot(self, game):
        """Автоснимки во время игры (если включены): раз в N минут, когда файл успокоился
        и изменился с прошлого снимка. Хранятся последние 10."""
        minutes = int(getattr(game, 'snapshot_minutes', 0) or 0)
        if minutes <= 0:
            return
        now = time.time()
        if now - self._last_snapshot.get(game.id, now) < minutes * 60:
            return
        self._last_snapshot[game.id] = now
        game = self.store.get_game(game.id) or game
        for slot in game.slots:
            info = sync_manager.local_info(slot, use_cache=False)
            if not info or info.get('size') == 0 or now - info.get('mtime', 0) < self.store.settings.periodic_stable_sec:
                continue
            excludes = sync_manager.parse_excludes(slot.exclude_patterns) if slot.is_directory else ()
            sig = sync_manager.stat_signature(slot.path, slot.is_directory, excludes)
            if sig is None:
                continue
            limit_mb = int(RUNTIME.get('max_auto_snapshot_mb', 0) or 0)
            if limit_mb and sig[0] > limit_mb * 1024 * 1024:
                if (game.id, slot.id) not in self._snap_too_big:
                    self._snap_too_big.add((game.id, slot.id))
                    log_action('snapshot', 'skip', f'{game.name} / {slot.label}: больше {limit_mb} МБ — автоснимки отключены для слота')
                continue
            if self._snap_sig.get((game.id, slot.id)) == sig:
                continue    # по stat ничего не менялось — содержимое не перечитываем
            fp = sync_manager.compute_fingerprint(slot.path, slot.is_directory, excludes)
            self._snap_sig[(game.id, slot.id)] = sig
            if fp is None or self._snap_fp.get((game.id, slot.id)) == fp:
                continue
            self._snap_fp[(game.id, slot.id)] = fp
            try:
                backup.make_snapshot(game.id, slot.id, slot.path, slot.is_directory, auto=True)
                log_action('snapshot', 'auto', f'{game.name} / {slot.label}')
            except OSError as e:
                log_action('snapshot', 'fail', str(e))

    def _maybe_periodic_upload(self, game):
        """Необязательная выгрузка раз в N минут во время игры (страховка от вылета).
        Безопасна: берёт только «успокоившиеся» файлы и использует ту же проверку
        облака, что и автовыгрузка при закрытии (новее/конфликт — пропуск)."""
        minutes = int(getattr(game, 'periodic_upload_minutes', 0) or 0)
        if minutes <= 0 or not game.account_id:
            return
        now = time.time()
        if now - self._last_periodic.get(game.id, now) < minutes * 60:
            return
        self._last_periodic[game.id] = now
        game = self.store.get_game(game.id) or game
        results = []
        for slot in game.slots:
            if not slot.path or not os.path.exists(slot.path):
                continue
            info = sync_manager.local_info(slot, use_cache=False)
            if not info or now - info.get('mtime', 0) < self.store.settings.periodic_stable_sec:
                continue  # файл только что писался — не рискуем прочитать наполовину записанным
            try:
                outcome, message, status = sync_manager.auto_upload_slot(self.store, game, slot)
            except Exception as e:
                outcome, message, status = 'error', str(e), {}
            if outcome == 'skipped':
                self.sync_check_result.emit(game.id, slot.id, status)
            if outcome != 'unchanged':
                # Ключ — id слота: два слота могут иметь одинаковое имя, и
                # сопоставление по label перемешало бы их результаты.
                results.append((slot.id, outcome == 'uploaded', message))
        log_action('periodic_upload', 'done', f'{game.name}: {len(results)} слотов')
        if results:
            self.periodic_result.emit(game.id, results)

    def _process_retries(self):
        """Повторяет неудачные автовыгрузки (нет сети, облако недоступно)."""
        now = time.time()
        for game_id, info in list(self._retries.items()):
            if info['due'] > now:
                continue
            game = self.store.get_game(game_id)
            if not game or not game.auto_upload_on_exit or self._was_running(game_id):
                # игру удалили/отключили автовыгрузку/запустили снова — выгрузка
                # произойдёт после следующего закрытия
                self._retries.pop(game_id, None)
                continue
            self._retries.pop(game_id, None)
            self._auto_upload_after_exit(game, attempt=info['attempt'])

    def _auto_upload_after_exit(self, game, attempt: int = 0):
        # Берём актуальный объект игры из хранилища (его могли изменить в UI).
        game = self.store.get_game(game.id) or game
        if not game.account_id:
            log_action('auto_upload', 'fail', f'{game.name}: не выбран облачный аккаунт')
            # Раньше здесь подставлялось имя игры: ключ не совпадал ни с одним
            # слотом, и ошибка не отображалась в карточке.
            self.upload_result.emit(game.id, [(s.id, False, 'Не выбран облачный аккаунт.')
                                              for s in game.slots])
            return
        results = []
        had_error = False
        for slot in game.slots:
            if not slot.path:
                continue
            try:
                outcome, message, status = sync_manager.auto_upload_slot(self.store, game, slot)
            except Exception as e:  # сетевые/файловые сбои не должны ронять монитор
                outcome, message, status = 'error', str(e), {}
                log_action('auto_upload', 'exception', f'{game.name} / {slot.label}: {e}')
            if outcome == 'skipped':
                self.sync_check_result.emit(game.id, slot.id, status)
            if outcome == 'error':
                had_error = True
            results.append((slot.id, outcome in ('uploaded', 'unchanged'), message))
        will_retry = False
        if had_error and self.store.settings.retry_failed_uploads and attempt < len(RETRY_DELAYS):
            delay = RETRY_DELAYS[attempt]
            self._retries[game.id] = {'attempt': attempt + 1, 'due': time.time() + delay}
            will_retry = True
            log_action('auto_upload', 'retry_scheduled', f'{game.name}: через {delay} с (попытка {attempt + 1})')
            results = [(label, ok, msg if ok else f'{msg} (повторим автоматически)')
                       for label, ok, msg in results]
        # при повторах уведомляем только о первой неудаче и об итоге
        if results and (attempt == 0 or not will_retry):
            self.upload_result.emit(game.id, results)
