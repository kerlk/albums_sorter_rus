#!/usr/bin/env python3
"""
Music Library Sorter v1.2 — сортировка музыкальных папок по типам: LP, EP, Singles.
Добавлено: обработка одиночных файлов в корне, удаление пустых папок.
"""

import os
import re
import sys
import shutil
import logging
import argparse
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Set, Tuple, Optional

try:
    from mutagen import File as MutagenFile
    HAS_MUTAGEN = True
except ImportError:
    HAS_MUTAGEN = False
    print("ВНИМАНИЕ: mutagen не установлен. Используется только анализ имён файлов.")
    print("Установите: pip install mutagen")

LOG_FILE = Path.home() / 'music_sorter.log'

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)
logger = logging.getLogger(__name__)

if sys.version_info < (3, 6):
    raise SystemExit("Требуется Python 3.6 или новее")


class TrackMetadata:
    """Метаданные аудиофайла."""
    def __init__(self):
        self.title = ""
        self.artist = ""
        self.album = ""
        self.track_number = 0
        self.duration = 0.0

    def clean_title(self) -> str:
        """Название без скобок, в нижнем регистре."""
        if not self.title:
            return ""
        t = re.sub(r'\([^)]*\)', '', self.title)
        t = re.sub(r'\[[^\]]*\]', '', t)
        t = t.lower().strip()
        return t


class MusicFolderSorter:
    """Сортирует папки по типам: LP, EP, Singles."""

    def __init__(self, root_path: str, dry_run: bool = True, delete_empty: bool = True):
        self.root_path = Path(root_path).resolve()
        self.dry_run = dry_run
        self.delete_empty = delete_empty
        self.audio_extensions = {
            '.mp3', '.flac', '.wav', '.m4a', '.aac', '.ogg', '.wma', '.opus',
            '.aiff', '.alac', '.ape', '.dsf', '.dff', '.mka', '.tta', '.wv'
        }
        self.metadata_cache: Dict[Path, TrackMetadata] = {}
        
        # Папки для сортировки
        self.lp_dir = self.root_path / "LP"
        self.ep_dir = self.root_path / "EP"
        self.singles_dir = self.root_path / "Singles"
        
        # Результаты
        self.lp_folders: List[Path] = []
        self.ep_folders: List[Path] = []
        self.single_folders: List[Path] = []
        self.unknown_folders: List[Path] = []
        self.empty_folders: List[Path] = []
        self.loose_files: List[Path] = []

    def is_audio_file(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.audio_extensions

    def has_audio_files(self, folder: Path) -> bool:
        """Проверяет, есть ли в папке аудиофайлы (рекурсивно)."""
        try:
            for item in folder.rglob('*'):
                if item.is_file() and self.is_audio_file(item):
                    return True
        except Exception as e:
            logger.warning(f"Ошибка проверки папки {folder}: {e}")
        return False

    def get_metadata(self, file_path: Path) -> Optional[TrackMetadata]:
        """Читает метаданные с кешированием."""
        if file_path in self.metadata_cache:
            return self.metadata_cache[file_path]
        if not HAS_MUTAGEN:
            return None
        try:
            audio = MutagenFile(str(file_path))
            if audio is None:
                return None
            meta = TrackMetadata()
            tags = getattr(audio, 'tags', None)
            if tags:
                for key in ('title', 'TIT2'):
                    if key in tags:
                        meta.title = str(tags[key][0])
                        break
                for key in ('artist', 'TPE1'):
                    if key in tags:
                        meta.artist = str(tags[key][0])
                        break
                for key in ('album', 'TALB'):
                    if key in tags:
                        meta.album = str(tags[key][0])
                        break
                for key in ('tracknumber', 'TRCK'):
                    if key in tags:
                        try:
                            meta.track_number = int(str(tags[key][0]).split('/')[0])
                        except:
                            pass
                        break
            info = getattr(audio, 'info', None)
            if info:
                meta.duration = getattr(info, 'length', 0.0) or 0.0
            self.metadata_cache[file_path] = meta
            return meta
        except Exception as e:
            logger.warning(f"Ошибка чтения метаданных {file_path}: {e}")
            return None

    def get_base_name(self, filename: str) -> str:
        """Извлекает базовое имя трека из имени файла (до первой скобки)."""
        stem = Path(filename).stem.lower()
        for bracket in ['(', '[']:
            if bracket in stem:
                stem = stem.split(bracket)[0]
                break
        stem = re.sub(r'^\d+[\s\-\._]+', '', stem)
        stem = re.sub(r'[\-_\.]+', ' ', stem)
        stem = ' '.join(stem.split())
        return stem

    def classify_folder(self, folder: Path) -> str:
        """
        Классифицирует папку:
        - 'single': >=50% файлов имеют одинаковое базовое имя (ремиксы одного трека)
        - 'ep': 2-6 файлов, нет доминирующего имени
        - 'lp': >=7 файлов, нет доминирующего имени
        - 'empty': нет аудиофайлов
        - 'unknown': не удалось определить
        """
        audio_files = [f for f in folder.iterdir() if f.is_file() and self.is_audio_file(f)]
        if not audio_files:
            return 'empty'
        
        total = len(audio_files)
        
        # Собираем базовые имена (из метаданных или имён файлов)
        base_names = []
        for f in audio_files:
            meta = self.get_metadata(f)
            if meta and meta.title:
                base = meta.clean_title()
            else:
                base = self.get_base_name(f.name)
            if base:
                base_names.append(base)
        
        if not base_names:
            return 'unknown'
        
        # Считаем частоту базовых имён
        counts = defaultdict(int)
        for name in base_names:
            counts[name] += 1
        
        max_count = max(counts.values())
        ratio = max_count / total
        
        # Singles: >=50% файлов имеют одинаковое базовое имя
        if ratio >= 0.5 and total >= 2:
            return 'single'
        
        # EP: 2-6 файлов
        if 2 <= total <= 6:
            return 'ep'
        
        # LP: >=7 файлов
        if total >= 7:
            return 'lp'
        
        return 'unknown'

    def scan_folders(self):
        """Сканирует все подпапки и классифицирует их."""
        logger.info(f"Сканирование: {self.root_path}")
        print(f"Сканирование: {self.root_path}")
        
        # Сканируем только непосредственные подпапки (не рекурсивно)
        for folder in self.root_path.iterdir():
            if not folder.is_dir():
                continue
            # Пропускаем папки, которые уже являются целевыми
            if folder.name in ['LP', 'EP', 'Singles']:
                continue
            
            folder_type = self.classify_folder(folder)
            
            if folder_type == 'single':
                self.single_folders.append(folder)
                print(f"  Singles: {folder.name}")
            elif folder_type == 'ep':
                self.ep_folders.append(folder)
                print(f"  EP: {folder.name}")
            elif folder_type == 'lp':
                self.lp_folders.append(folder)
                print(f"  LP: {folder.name}")
            elif folder_type == 'empty':
                self.empty_folders.append(folder)
                print(f"  Empty (будет удалена): {folder.name}")
            else:
                self.unknown_folders.append(folder)
                print(f"  Unknown: {folder.name}")

    def scan_loose_files(self):
        """Сканирует одиночные аудиофайлы в корневой директории."""
        self.loose_files = [f for f in self.root_path.iterdir() if f.is_file() and self.is_audio_file(f)]
        
        if self.loose_files:
            print(f"\nОдиночные файлы в корне: {len(self.loose_files)}")
            for f in self.loose_files:
                print(f"  {f.name}")

    def move_folders(self):
        """Перемещает папки в соответствующие директории."""
        print(f"\n{'[ПРОВЕРКА] ' if self.dry_run else '[ПЕРЕМЕЩЕНИЕ] '}Сортировка папок:")
        
        # Создаём целевые директории
        for dir_path in [self.lp_dir, self.ep_dir, self.singles_dir]:
            if not self.dry_run:
                dir_path.mkdir(parents=True, exist_ok=True)
        
        # Перемещаем Singles
        for folder in self.single_folders:
            dest = self.singles_dir / folder.name
            self._move_folder(folder, dest, 'Singles')
        
        # Перемещаем EP
        for folder in self.ep_folders:
            dest = self.ep_dir / folder.name
            self._move_folder(folder, dest, 'EP')
        
        # Перемещаем LP
        for folder in self.lp_folders:
            dest = self.lp_dir / folder.name
            self._move_folder(folder, dest, 'LP')

    def process_loose_files(self):
        """Обрабатывает одиночные аудиофайлы в корневой директории."""
        if not self.loose_files:
            return
        
        print(f"\n{'[ПРОВЕРКА] ' if self.dry_run else '[ОБРАБОТКА] '}Одиночные файлы в корне:")
        
        for file_path in self.loose_files:
            # Создаём папку с именем файла (без расширения)
            folder_name = file_path.stem
            dest_folder = self.singles_dir / folder_name
            
            print(f"  {file_path.name} -> {dest_folder}/")
            
            if not self.dry_run:
                try:
                    dest_folder.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(file_path), str(dest_folder / file_path.name))
                    logger.info(f"Перемещён файл {file_path} -> {dest_folder}")
                except Exception as e:
                    print(f"    Ошибка: {e}")
                    logger.error(f"Ошибка перемещения {file_path}: {e}")

    def delete_empty_folders(self):
        """Удаляет пустые папки (без аудиофайлов)."""
        if not self.delete_empty:
            return
        
        if not self.empty_folders:
            print("\nПустые папки не найдены.")
            return
        
        print(f"\n{'[ПРОВЕРКА] ' if self.dry_run else '[УДАЛЕНИЕ] '}Удаление пустых папок:")
        for folder in self.empty_folders:
            try:
                if self.dry_run:
                    print(f"  Будет удалена: {folder}")
                else:
                    # Проверяем ещё раз, что папка действительно пустая (без аудио)
                    if not self.has_audio_files(folder):
                        shutil.rmtree(folder)
                        print(f"  Удалена: {folder}")
                        logger.info(f"Удалена пустая папка: {folder}")
                    else:
                        print(f"  Пропущена (содержит аудио): {folder}")
            except Exception as e:
                print(f"  Ошибка удаления {folder}: {e}")
                logger.error(f"Ошибка удаления {folder}: {e}")

    def _move_folder(self, source: Path, dest: Path, folder_type: str):
        """Перемещает папку с обработкой конфликтов имён."""
        counter = 1
        original_dest = dest
        while dest.exists():
            dest = original_dest.parent / f"{original_dest.name}_{counter}"
            counter += 1
        
        print(f"  [{folder_type}] {source.name} -> {dest}")
        
        if not self.dry_run:
            try:
                shutil.move(str(source), str(dest))
                logger.info(f"Перемещена папка {source} -> {dest}")
            except Exception as e:
                print(f"    Ошибка: {e}")
                logger.error(f"Ошибка перемещения {source}: {e}")

    def generate_report(self) -> str:
        """Создаёт отчёт о сортировке."""
        lines = []
        lines.append("=" * 60)
        lines.append("ОТЧЁТ О СОРТИРОВКЕ МУЗЫКАЛЬНЫХ ПАПОК")
        lines.append("=" * 60)
        lines.append(f"Корневая директория: {self.root_path}")
        lines.append(f"LP: {len(self.lp_folders)} папок")
        lines.append(f"EP: {len(self.ep_folders)} папок")
        lines.append(f"Singles: {len(self.single_folders)} папок")
        lines.append(f"Одиночные файлы: {len(self.loose_files)}")
        lines.append(f"Empty (удалены): {len(self.empty_folders)} папок")
        lines.append(f"Unknown: {len(self.unknown_folders)} папок")
        
        if self.lp_folders:
            lines.append("\nLP (альбомы):")
            for f in self.lp_folders:
                lines.append(f"  - {f.name}")
        
        if self.ep_folders:
            lines.append("\nEP (мини-альбомы):")
            for f in self.ep_folders:
                lines.append(f"  - {f.name}")
        
        if self.single_folders:
            lines.append("\nSingles (синглы):")
            for f in self.single_folders:
                lines.append(f"  - {f.name}")
        
        if self.loose_files:
            lines.append("\nОдиночные файлы (перемещены в Singles/):")
            for f in self.loose_files:
                lines.append(f"  - {f.name}")
        
        if self.empty_folders:
            lines.append("\nEmpty (пустые папки):")
            for f in self.empty_folders:
                lines.append(f"  - {f.name}")
        
        if self.unknown_folders:
            lines.append("\nUnknown (не определено):")
            for f in self.unknown_folders:
                lines.append(f"  - {f.name}")
        
        lines.append("=" * 60)
        return "\n".join(lines)

    def run(self):
        """Запускает процесс сортировки."""
        self.scan_folders()
        self.scan_loose_files()
        self.move_folders()
        self.process_loose_files()
        self.delete_empty_folders()
        
        report = self.generate_report()
        print("\n" + report)
        
        # Сохраняем отчёт
        report_file = self.root_path / "sorting_report.txt"
        if not self.dry_run:
            try:
                with open(report_file, 'w', encoding='utf-8') as f:
                    f.write(report)
                print(f"\nОтчёт сохранён: {report_file}")
            except Exception as e:
                print(f"Не удалось сохранить отчёт: {e}")


# ---------- Интерактивный интерфейс ----------

def print_menu():
    print("\n" + "=" * 60)
    print("MUSIC LIBRARY SORTER v1.2")
    print("=" * 60)
    print("\nТекущая директория:", os.getcwd())
    print("\nВыберите действие:")
    print("1. Сортировать папки (LP, EP, Singles) + удалить пустые")
    print("2. Только удалить пустые папки (без аудиофайлов)")
    print("3. Сменить рабочую директорию")
    print("4. Выход")
    print("\n" + "=" * 60)


def get_user_choice() -> int:
    while True:
        try:
            choice = input("\nВаш выбор (1-4): ").strip()
            if choice in ['1', '2', '3', '4']:
                return int(choice)
            else:
                print("Ошибка: введите число от 1 до 4")
        except KeyboardInterrupt:
            print("\nВыход...")
            sys.exit(0)


def get_dry_run_choice() -> bool:
    print("\nРежим работы:")
    print("1. Проверка (dry run) - показать, что будет сделано")
    print("2. Выполнить реальные операции")
    while True:
        try:
            choice = input("Ваш выбор (1-2): ").strip()
            if choice == '1':
                return True
            elif choice == '2':
                return False
            else:
                print("Ошибка: введите 1 или 2")
        except KeyboardInterrupt:
            print("\nВыход...")
            sys.exit(0)


def confirm_action(prompt: str = "Продолжить? (y/n): ") -> bool:
    while True:
        try:
            ans = input(prompt).strip().lower()
            if ans in ['y', 'yes', 'да']:
                return True
            elif ans in ['n', 'no', 'нет']:
                return False
            else:
                print("Введите y или n")
        except KeyboardInterrupt:
            print("\nОтменено")
            return False


def main():
    parser = argparse.ArgumentParser(description='Music Library Sorter')
    parser.add_argument('path', nargs='?', help='Путь к музыкальной библиотеке (по умолчанию - текущая директория)')
    parser.add_argument('--no-delete-empty', action='store_true', help='Не удалять пустые папки')
    args = parser.parse_args()

    if args.path:
        music_path = args.path
    else:
        music_path = os.getcwd()
        print(f"Используется текущая директория: {music_path}")

    if not os.path.exists(music_path):
        print(f"Ошибка: директория {music_path} не существует")
        sys.exit(1)
    if not os.path.isdir(music_path):
        print(f"Ошибка: {music_path} не является директорией")
        sys.exit(1)

    os.chdir(music_path)
    print(f"\nМузыкальная библиотека: {music_path}")
    
    if HAS_MUTAGEN:
        print("Анализ метаданных: ВКЛЮЧЁН")
    else:
        print("Анализ метаданных: ОТКЛЮЧЁН (установите mutagen)")

    while True:
        print_menu()
        choice = get_user_choice()

        if choice == 4:
            print("\nВыход из программы. До свидания!")
            break

        if choice == 3:
            new_path = input("Введите новый путь к музыкальной библиотеке: ").strip()
            if os.path.isdir(new_path):
                os.chdir(new_path)
                music_path = new_path
                print(f"Рабочая директория изменена на: {music_path}")
            else:
                print("Ошибка: директория не существует")
            continue

        if choice == 1:
            dry_run = get_dry_run_choice()
            if not dry_run:
                if not confirm_action("Вы уверены, что хотите выполнить РЕАЛЬНЫЕ операции? (y/n): "):
                    print("Операция отменена.")
                    continue

            sorter = MusicFolderSorter(
                root_path=os.getcwd(),
                dry_run=dry_run,
                delete_empty=not args.no_delete_empty
            )
            sorter.run()

        elif choice == 2:
            dry_run = get_dry_run_choice()
            if not dry_run:
                if not confirm_action("Вы уверены, что хотите удалить пустые папки? (y/n): "):
                    print("Операция отменена.")
                    continue

            sorter = MusicFolderSorter(
                root_path=os.getcwd(),
                dry_run=dry_run,
                delete_empty=True
            )
            # Только сканируем и удаляем пустые
            sorter.scan_folders()
            sorter.delete_empty_folders()

        if choice in [1, 2]:
            try:
                input("\nНажмите Enter для продолжения...")
            except KeyboardInterrupt:
                print("\nВыход...")
                sys.exit(0)

        if os.name == 'nt':
            os.system('cls')
        else:
            os.system('clear')


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nПрограмма прервана пользователем")
        sys.exit(0)
