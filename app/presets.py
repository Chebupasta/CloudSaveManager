"""
Встроенные пресеты для известных игр без облачных сохранений.
Пресет описывает: как называется игра, какие процессы отслеживать,
и как автоматически найти файлы сохранений на диске.

Пользователь всегда может создать свою собственную игру ("Другая игра"),
указав путь к файлу/папке сохранения вручную — пресеты лишь ускоряют
настройку для нескольких распространённых игр.
"""
from dataclasses import dataclass
from typing import List, Optional

from app.path_utils import find_slot_files


@dataclass
class SlotPreset:
    key: str
    label: str
    filename: str
    folder_name: str
    steam_app_id: str
    remote_name: str
    is_directory: bool = False


@dataclass
class GamePreset:
    key: str
    name: str
    process_names: List[str]
    slots: List[SlotPreset]


PRESETS = {
    'ds3': GamePreset(
        key='ds3',
        name='Dark Souls III',
        process_names=['DarkSoulsIII.exe'],
        slots=[
            SlotPreset('ds3_orig', 'Оригинальная игра', 'DS30000.sl2',
                       'DarkSoulsIII', '374320', 'DS30000.sl2'),
            SlotPreset('ds3_coop', 'Seamless Co-op', 'DS30000.co2',
                       'DarkSoulsIII', '374320', 'DS30000.co2'),
        ],
    ),
    'elden_ring': GamePreset(
        key='elden_ring',
        name='Elden Ring',
        process_names=['eldenring.exe'],
        slots=[
            SlotPreset('er_orig', 'Оригинальная игра', 'ER0000.sl2',
                       'EldenRing', '1245620', 'ER0000.sl2'),
            SlotPreset('er_coop', 'Seamless Co-op', 'ER0000.co2',
                       'EldenRing', '1245620', 'ER0000.co2'),
        ],
    ),
    'custom': GamePreset(
        key='custom',
        name='Другая игра (указать вручную)',
        process_names=[],
        slots=[],
    ),
}


def get_preset(key: str) -> Optional[GamePreset]:
    return PRESETS.get(key)


def get_slot_preset(detect_key: str) -> Optional[SlotPreset]:
    """Ищет SlotPreset по его detect_key среди всех встроенных пресетов."""
    for preset in PRESETS.values():
        for slot in preset.slots:
            if slot.key == detect_key:
                return slot
    return None


def detect_slot_paths(slot_preset: SlotPreset) -> List[str]:
    """Возвращает список найденных путей для данного пресета слота."""
    return find_slot_files(slot_preset.folder_name, slot_preset.filename,
                            slot_preset.steam_app_id)
