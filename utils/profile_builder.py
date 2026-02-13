"""
Построение расширенного профиля пользователя
"""
import logging
import re
from typing import Optional, Dict
from bs4 import BeautifulSoup

from config.settings import BASE_URL, REQUEST_TIMEOUT
from utils.sheets_parser import get_sheets_parser
from utils.helpers import site_session

logger = logging.getLogger(__name__)

CLUB_PAGE_URL = f"{BASE_URL}/clubs/klub-taro-2"


def get_club_contribution(profile_id: str) -> Optional[int]:
    """
    Парсит страницу клуба и извлекает вклад пользователя
    
    Ищет:
    <a href="/users/102979" class="club__member-image">
        <div class="club__member-contribution">160</div>
    </a>
    
    Args:
        profile_id: ID профиля пользователя (например, "102979")
    
    Returns:
        int: Вклад пользователя или None если не найден
    """
    if not site_session:
        logger.error("Сессия сайта не инициализирована")
        return None
    
    try:
        logger.debug(f"Загрузка страницы клуба для поиска вклада пользователя {profile_id}")
        response = site_session.get(CLUB_PAGE_URL, timeout=REQUEST_TIMEOUT)
        
        if response.status_code != 200:
            logger.error(f"Ошибка загрузки страницы клуба: {response.status_code}")
            return None
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Ищем ссылку на пользователя
        user_link = soup.find('a', href=f'/users/{profile_id}', class_='club__member-image')
        
        if not user_link:
            logger.warning(f"⚠️ Пользователь {profile_id} не найден на странице клуба")
            return None
        
        # Ищем div с вкладом внутри ссылки
        contribution_div = user_link.find('div', class_='club__member-contribution')
        
        if not contribution_div:
            logger.warning(f"⚠️ Вклад не найден для пользователя {profile_id}")
            return 0
        
        # Извлекаем число
        contribution_text = contribution_div.get_text(strip=True)
        contribution = int(contribution_text)
        
        logger.info(f"✅ Вклад пользователя {profile_id}: {contribution}")
        return contribution
        
    except Exception as e:
        logger.error(f"Ошибка получения вклада: {e}")
        return None


def calculate_total_contribution(column_l: str, column_j: str, club_contribution: int) -> int:
    """
    Рассчитывает общий вклад по формуле: L + J/2 + вклад_на_странице_клуба
    
    Args:
        column_l: Значение из столбца L (строка)
        column_j: Значение из столбца J (строка)
        club_contribution: Вклад со страницы клуба
    
    Returns:
        int: Общий вклад
    """
    try:
        # Конвертируем в числа, игнорируя пустые строки
        l_value = float(column_l) if column_l and column_l.strip() else 0
        j_value = float(column_j) if column_j and column_j.strip() else 0
        club_value = club_contribution if club_contribution is not None else 0
        
        total = l_value + (j_value / 2) + club_value
        
        logger.debug(f"Расчет вклада: {l_value} + {j_value}/2 + {club_value} = {total}")
        
        return int(total)
        
    except Exception as e:
        logger.error(f"Ошибка расчета вклада: {e}")
        return 0


def build_user_profile(user_data: Dict) -> Optional[Dict]:
    """
    ✅ ОБНОВЛЕНО: Использует новые методы парсера с правильной кодировкой
    
    Строит полный профиль пользователя из разных источников
    
    Args:
        user_data: Данные пользователя из БД
        {
            'user_id': int,
            'username': str,
            'first_name': str,
            'last_name': str,
            'profile_url': str,
            'profile_id': str,
            'site_nickname': str,
        }
    
    Returns:
        Dict с полным профилем или None в случае ошибки
        {
            'site_nickname': str,
            'telegram_display': str,
            'arcana': str,
            'sequence': str,
            'balance': str,
            'contribution': int,
            'inventory': str,
        }
    """
    try:
        profile_url = user_data.get('profile_url')
        profile_id = user_data.get('profile_id')
        
        if not profile_url or not profile_id:
            logger.error("Отсутствует profile_url или profile_id")
            return None
        
        # 1. Ник с сайта (уже есть в БД)
        site_nickname = user_data.get('site_nickname', 'Неизвестный')
        
        # 2. Имя/ссылка в Telegram
        telegram_display = user_data.get('first_name', '')
        if not telegram_display and user_data.get('username'):
            telegram_display = f"@{user_data['username']}"
        if not telegram_display:
            # Если нет ни имени, ни username - формируем ссылку
            telegram_display = f"<a href='tg://user?id={user_data['user_id']}'>Пользователь</a>"
        
        # ✅ 3-4-7. Данные из листа инвентаря (аркана, последовательность, инвентарь)
        parser = get_sheets_parser()
        inventory_data = parser.get_user_inventory_data(profile_url)
        
        if not inventory_data:
            logger.warning("⚠️ Данные пользователя не найдены в листе инвентаря")
            # Пробуем хотя бы получить баланс
            main_data = parser.get_user_main_data(profile_url)
            
            return {
                'site_nickname': site_nickname,
                'telegram_display': telegram_display,
                'arcana': 'Не указана',
                'sequence': 'Не указана',
                'balance': main_data.get('balance', '0') if main_data else '0',
                'contribution': 0,
                'inventory': 'Не указан',
            }
        
        # Аркана (столбец D)
        arcana = inventory_data.get('arcana', 'Не указана')
        
        # Последовательность (столбцы H и G)
        sequence_name = inventory_data.get('sequence', '')
        sequence_number = inventory_data.get('sequence_number', '')
        if sequence_name and sequence_number:
            sequence = f"{sequence_name} ({sequence_number})"
        elif sequence_name:
            sequence = sequence_name
        else:
            sequence = 'Не указана'
        
        # Инвентарь (столбец J)
        inventory = inventory_data.get('inventory', '')
        if not inventory:
            inventory = 'Не указан'
        
        # ✅ 5-6. Баланс и вклад из основного листа
        main_data = parser.get_user_main_data(profile_url)
        
        if not main_data:
            logger.warning("⚠️ Данные пользователя не найдены в основном листе")
            balance = '0'
            contribution = 0
        else:
            # Баланс
            balance = main_data.get('balance', '0')
            
            # Вклад (расчет)
            club_contribution = get_club_contribution(profile_id)
            contribution = calculate_total_contribution(
                main_data.get('column_l', '0'),
                main_data.get('column_j', '0'),
                club_contribution
            )
        
        profile = {
            'site_nickname': site_nickname,
            'telegram_display': telegram_display,
            'arcana': arcana,
            'sequence': sequence,
            'balance': balance,
            'contribution': contribution,
            'inventory': inventory,
        }
        
        logger.info(f"✅ Профиль пользователя {profile_id} успешно построен")
        return profile
        
    except Exception as e:
        logger.error(f"Ошибка построения профиля: {e}", exc_info=True)
        return None


def format_profile_message(profile: Dict) -> str:
    """
    Форматирует профиль для отправки в Telegram
    
    Args:
        profile: Данные профиля из build_user_profile
    
    Returns:
        str: Отформатированное сообщение в HTML
    """
    return (
        f"👤 <b>Профиль пользователя</b>\n\n"
        f"🌐 <b>Ник MangaBuff:</b> {profile['site_nickname']}\n"
        f"📱 <b>Telegram:</b> {profile['telegram_display']}\n\n"
        f"🃏 <b>Аркана:</b> {profile['arcana']}\n"
        f"⚡️ <b>Последовательность:</b> {profile['sequence']}\n\n"
        f"💰 <b>Баланс:</b> {profile['balance']} ОК\n"
        f"📊 <b>Вклад:</b> {profile['contribution']}\n\n"
        f"🎒 <b>Инвентарь:</b>\n{profile['inventory']}"
    )