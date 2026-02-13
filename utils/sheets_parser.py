"""
Парсер данных из Google Sheets для профилей пользователей
✅ ИСПРАВЛЕНО: Правильная обработка UTF-8 кодировки
✅ ОБНОВЛЕНО: Все данные теперь берутся с листа инвентаря
"""
import logging
import csv
import requests
from typing import Optional, Dict
from io import StringIO

logger = logging.getLogger(__name__)

# ID таблицы и листов
SPREADSHEET_ID = "1sYvrBU9BPhcoxTnNJfx8TOutxwFrSiRm2mw_8s6rdZM"
MAIN_SHEET_GID = "846561775"  # Основной лист (для баланса и вклада)
INVENTORY_SHEET_GID = "1142214254"  # Лист инвентаря (для арканы, последовательности, инвентаря)

# URL для экспорта в CSV
MAIN_SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={MAIN_SHEET_GID}"
INVENTORY_SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={INVENTORY_SHEET_GID}"


class SheetsParser:
    """Парсер данных из Google Sheets"""
    
    def __init__(self):
        self.main_data_cache = None
        self.inventory_data_cache = None
    
    def _download_sheet(self, url: str) -> Optional[list]:
        """
        Скачивает и парсит Google Sheet как CSV
        ✅ ИСПРАВЛЕНО: Правильная обработка UTF-8
        Возвращает список строк (каждая строка - список значений)
        """
        try:
            logger.debug(f"Загрузка таблицы: {url}")
            response = requests.get(url, timeout=30)
            
            if response.status_code != 200:
                logger.error(f"Ошибка загрузки таблицы: {response.status_code}")
                return None
            
            # ✅ ИСПРАВЛЕНИЕ: Явно указываем UTF-8 кодировку
            response.encoding = 'utf-8'
            
            # Парсим CSV с UTF-8
            csv_data = StringIO(response.text)
            reader = csv.reader(csv_data)
            rows = list(reader)
            
            logger.info(f"✅ Таблица загружена: {len(rows)} строк")
            return rows
            
        except Exception as e:
            logger.error(f"Ошибка загрузки таблицы: {e}")
            return None
    
    def _column_letter_to_index(self, letter: str) -> int:
        """Конвертирует букву колонки в индекс (A=0, B=1, ..., Z=25, AA=26)"""
        result = 0
        for char in letter.upper():
            result = result * 26 + (ord(char) - ord('A') + 1)
        return result - 1
    
    def get_user_inventory_data(self, profile_url: str, force_refresh: bool = False) -> Optional[Dict]:
        """
        ✅ ОБНОВЛЕНО: Получает данные с листа инвентаря
        
        Теперь возвращает:
        {
            'arcana': str,           # Столбец D
            'sequence': str,         # Столбец H
            'sequence_number': str,  # Столбец G
            'inventory': str,        # Столбец J
        }
        """
        # Загружаем данные если нужно
        if self.inventory_data_cache is None or force_refresh:
            self.inventory_data_cache = self._download_sheet(INVENTORY_SHEET_URL)
        
        if not self.inventory_data_cache:
            logger.error("Не удалось загрузить лист инвентаря")
            return None
        
        # Индексы столбцов (A=0, B=1, C=2, ...)
        COL_A = 0   # Profile URL
        COL_D = 3   # ✅ Аркана
        COL_G = 6   # ✅ Номер последовательности (в скобках)
        COL_H = 7   # ✅ Последовательность (название)
        COL_J = 9   # Инвентарь
        
        # Ищем строку с совпадением по profile_url
        for row_idx, row in enumerate(self.inventory_data_cache):
            # Пропускаем заголовок
            if row_idx == 0:
                continue
            
            # Проверяем достаточно ли колонок
            if len(row) <= COL_A:
                continue
            
            # Проверяем совпадение URL (столбец A)
            if row[COL_A].strip() == profile_url.strip():
                logger.info(f"✅ Найден пользователь в листе инвентаря: строка {row_idx + 1}")
                
                return {
                    'arcana': row[COL_D].strip() if len(row) > COL_D else '',
                    'sequence': row[COL_H].strip() if len(row) > COL_H else '',
                    'sequence_number': row[COL_G].strip() if len(row) > COL_G else '',
                    'inventory': row[COL_J].strip() if len(row) > COL_J else '',
                }
        
        logger.warning(f"⚠️ Пользователь не найден в листе инвентаря: {profile_url}")
        return None
    
    def get_user_main_data(self, profile_url: str, force_refresh: bool = False) -> Optional[Dict]:
        """
        ✅ ОБНОВЛЕНО: Получает только баланс и данные для вклада с основного листа
        
        Возвращает:
        {
            'balance': str,          # Столбец P
            'column_l': str,         # Столбец L (для расчета вклада)
            'column_j': str,         # Столбец J (для расчета вклада)
        }
        """
        # Загружаем данные если нужно
        if self.main_data_cache is None or force_refresh:
            self.main_data_cache = self._download_sheet(MAIN_SHEET_URL)
        
        if not self.main_data_cache:
            logger.error("Не удалось загрузить основной лист")
            return None
        
        # Индексы столбцов (A=0, B=1, C=2, ...)
        COL_B = 1   # Profile URL
        COL_J = 9   # J (для вклада)
        COL_L = 11  # L (для вклада)
        COL_P = 15  # Баланс ОК
        
        # Ищем строку с совпадением по profile_url
        for row_idx, row in enumerate(self.main_data_cache):
            # Пропускаем заголовок
            if row_idx == 0:
                continue
            
            # Проверяем достаточно ли колонок
            if len(row) <= COL_B:
                continue
            
            # Проверяем совпадение URL (столбец B)
            if row[COL_B].strip() == profile_url.strip():
                logger.info(f"✅ Найден пользователь в основном листе: строка {row_idx + 1}")
                
                return {
                    'balance': row[COL_P].strip() if len(row) > COL_P else '0',
                    'column_l': row[COL_L].strip() if len(row) > COL_L else '0',
                    'column_j': row[COL_J].strip() if len(row) > COL_J else '0',
                }
        
        logger.warning(f"⚠️ Пользователь не найден в основном листе: {profile_url}")
        return None
    
    def clear_cache(self):
        """Очищает кеш данных (для принудительного обновления)"""
        self.main_data_cache = None
        self.inventory_data_cache = None
        logger.info("🗑️ Кеш таблиц очищен")


# Глобальный экземпляр парсера
_parser_instance = None


def get_sheets_parser() -> SheetsParser:
    """Возвращает глобальный экземпляр парсера"""
    global _parser_instance
    if _parser_instance is None:
        _parser_instance = SheetsParser()
    return _parser_instance