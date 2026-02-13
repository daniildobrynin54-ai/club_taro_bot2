"""
Утилиты для бота
✅ ОБНОВЛЕНО: Добавлена функция get_site_nickname для получения ника с сайта
"""
import logging
import re
import requests
from typing import Optional, Tuple
from bs4 import BeautifulSoup
from config.settings import (
    BASE_URL, SITE_EMAIL, SITE_PASSWORD, 
    USER_AGENT, REQUEST_TIMEOUT, TELEGRAM_GROUP_ID
)
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# Целевой клуб
CLUB_HREF = "/clubs/klub-taro-2"
CLUB_CLASS = "club-top-list__name"

# Глобальная сессия для сайта
site_session = None
csrf_token = None


def get_user_link(user_id: int, name: str = None) -> str:
    """Возвращает ссылку на пользователя Telegram"""
    display_name = name if name else f"User {user_id}"
    return f'<a href="tg://user?id={user_id}">{display_name}</a>'


def get_csrf_token(session: requests.Session) -> Optional[str]:
    """Получает CSRF токен со страницы логина."""
    try:
        logger.debug("Запрос CSRF токена")
        response = session.get(f"{BASE_URL}/login", timeout=REQUEST_TIMEOUT)
        
        if response.status_code != 200:
            logger.error(f"Ошибка получения страницы логина: статус {response.status_code}")
            return None
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        token_meta = soup.select_one('meta[name="csrf-token"]')
        if token_meta:
            token = token_meta.get("content", "").strip()
            if token:
                logger.debug("CSRF токен найден в meta теге")
                return token
        
        token_input = soup.find("input", {"name": "_token"})
        if token_input:
            token = token_input.get("value", "").strip()
            if token:
                logger.debug("CSRF токен найден в input поле")
                return token
        
        logger.warning("CSRF токен не найден на странице")
        return None
        
    except requests.RequestException as e:
        logger.error(f"Ошибка при получении CSRF токена: {e}")
        return None


def is_authenticated(session: requests.Session) -> bool:
    """Проверяет, авторизована ли сессия."""
    return "mangabuff_session" in session.cookies


def login_to_site() -> bool:
    """Выполняет вход в аккаунт на сайте."""
    global site_session, csrf_token
    
    logger.info("Попытка входа на сайт")
    site_session = requests.Session()
    
    site_session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru,en;q=0.8",
    })
    
    csrf_token = get_csrf_token(site_session)
    if not csrf_token:
        logger.error("Не удалось получить CSRF токен")
        return False
    
    headers = {
        "Referer": f"{BASE_URL}/login",
        "Origin": BASE_URL,
        "Content-Type": "application/x-www-form-urlencoded",
        "X-CSRF-TOKEN": csrf_token,
    }
    
    data = {
        "email": SITE_EMAIL,
        "password": SITE_PASSWORD,
        "_token": csrf_token
    }
    
    try:
        response = site_session.post(
            f"{BASE_URL}/login",
            data=data,
            headers=headers,
            allow_redirects=True,
            timeout=REQUEST_TIMEOUT
        )
        
        if not is_authenticated(site_session):
            logger.error("Авторизация не удалась - отсутствует сессионная кука")
            return False
        
        logger.info("✅ Успешная авторизация на сайте")
        return True
        
    except requests.RequestException as e:
        logger.error(f"Ошибка при авторизации: {e}")
        return False


def get_site_nickname(profile_url: str) -> Optional[str]:
    """
    ✅ НОВАЯ ФУНКЦИЯ: Получает ник пользователя с сайта
    
    Парсит страницу профиля и извлекает ник из:
    <div class="profile__name" data-name="your Kasandra" ...>your Kasandra</div>
    
    Args:
        profile_url: Ссылка на профиль (https://mangabuff.ru/users/XXXXXX)
    
    Returns:
        str: Ник пользователя или None если не удалось получить
    """
    global site_session
    
    if not site_session or not is_authenticated(site_session):
        logger.warning("Сессия не авторизована, пытаемся войти заново")
        if not login_to_site():
            logger.error("Не удалось авторизоваться для получения ника")
            return None
    
    try:
        response = site_session.get(profile_url, timeout=REQUEST_TIMEOUT)
        
        if response.status_code != 200:
            logger.warning(f"Профиль недоступен при получении ника: {response.status_code}")
            return None
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Ищем div с классом profile__name
        name_div = soup.find("div", class_="profile__name")
        
        if name_div:
            # Берем текст из div или из атрибута data-name
            nickname = name_div.get("data-name", "").strip()
            if not nickname:
                nickname = name_div.get_text(strip=True)
            
            if nickname:
                logger.info(f"Получен ник с сайта: {nickname} (профиль: {profile_url})")
                return nickname
        
        logger.warning(f"Не удалось найти ник на странице {profile_url}")
        return None
            
    except requests.RequestException as e:
        logger.error(f"Ошибка при получении ника: {e}")
        return None


def check_club_membership(profile_url: str) -> Tuple[bool, str]:
    """
    Проверяет членство пользователя в клубе на сайте.

    Ищет на странице профиля элемент:
        <a href="/clubs/klub-taro-2" class="club-top-list__name">...</a>
    и сверяет, что атрибут href равен именно '/clubs/klub-taro-2'.
    """
    global site_session
    
    if not site_session or not is_authenticated(site_session):
        logger.warning("Сессия не авторизована, пытаемся войти заново")
        if not login_to_site():
            return False, "Ошибка авторизации на сайте"
    
    try:
        response = site_session.get(profile_url, timeout=REQUEST_TIMEOUT)
        
        if response.status_code != 200:
            logger.warning(f"Профиль недоступен: {response.status_code}")
            return False, f"Профиль недоступен (код {response.status_code})"
        
        soup = BeautifulSoup(response.text, "html.parser")

        # Ищем все <a> с классом club-top-list__name
        club_links = soup.find_all("a", class_=CLUB_CLASS)

        for link in club_links:
            href = link.get("href", "").strip()
            # Сверяем href строго — должен быть именно /clubs/klub-taro-2
            if href == CLUB_HREF:
                logger.info(f"Пользователь состоит в Club Taro (найден элемент '{CLUB_HREF}'): {profile_url}")
                return True, "Пользователь состоит в Club Taro"

        logger.info(f"Пользователь НЕ состоит в Club Taro (элемент '{CLUB_HREF}' не найден): {profile_url}")
        return False, "Вы не состоите в Club Taro"
            
    except requests.RequestException as e:
        logger.error(f"Ошибка при проверке членства: {e}")
        return False, f"Ошибка соединения: {e}"


async def is_user_in_group(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    """Проверяет, состоит ли пользователь в группе Telegram"""
    try:
        member = await context.bot.get_chat_member(chat_id=TELEGRAM_GROUP_ID, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Ошибка проверки членства в группе: {e}")
        return False


def validate_profile_url(url: str) -> Optional[str]:
    """
    Проверяет формат URL профиля и возвращает ID профиля.
    Принимает ссылки формата: https://mangabuff.ru/users/XXXXXX
    где XXXXXX - от 1 до 7 цифр
    """
    url_pattern = r'https://mangabuff\.ru/users/(\d{1,7})$'
    match = re.match(url_pattern, url.strip())
    return match.group(1) if match else None
