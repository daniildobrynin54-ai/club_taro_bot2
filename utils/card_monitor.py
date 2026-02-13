"""
Мониторинг карт клуба на MangaBuff

✅ ИСПРАВЛЕН КРИТИЧЕСКИЙ БАГ:
  • Проверка наличия карты в БД теперь ПЕРЕД сохранением
  • Добавлено больше логирования для отладки
  • TELEGRAM_GROUP_ID конвертируется в int
"""
import logging
import re
import json
from datetime import datetime
from typing import Optional, Dict

import requests
from bs4 import BeautifulSoup
from telegram.constants import ParseMode

from config.settings import BASE_URL, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

BOOST_URL = f"{BASE_URL}/clubs/klub-taro-2/boost"


# ═════════════════════════════════════════════════════════════
# КЛАСС МОНИТОРА (без изменений)
# ═════════════════════════════════════════════════════════════

class CardMonitor:
    """Мониторинг карт клуба на MangaBuff"""

    def __init__(self, session: requests.Session):
        self.session = session
        self.last_card_id: Optional[str] = None
        self.initialized: bool = False

        # Детектор ранга — инициализируем сразу
        try:
            from utils.rank_detector import RankDetector
            self.rank_detector = RankDetector()
            if self.rank_detector.is_ready:
                logger.info(
                    f"✅ RankDetector готов. Доступные ранги: "
                    f"{', '.join(self.rank_detector.available_ranks)}"
                )
            else:
                logger.warning(
                    "⚠️  RankDetector: шаблоны не загружены. "
                    "Ранг будет отображаться как '?'. "
                    "Добавьте PNG-рамки в папку ranks/"
                )
        except Exception as e:
            logger.error(f"Ошибка инициализации RankDetector: {e}")
            self.rank_detector = None

    # ... (все остальные методы без изменений)
    
    def get_current_card_id(self) -> Optional[str]:
        """Загружает страницу boost и возвращает только ID карты"""
        try:
            r = self.session.get(BOOST_URL, timeout=REQUEST_TIMEOUT)
            if r.status_code != 200:
                logger.warning(f"Ошибка загрузки boost ({r.status_code})")
                return None

            soup = BeautifulSoup(r.text, 'html.parser')
            link = soup.find('a', href=re.compile(r'/cards/\d+/users'))
            if link:
                m = re.search(r'/cards/(\d+)/', link.get('href', ''))
                if m:
                    return m.group(1)

            logger.warning("ID карты не найден на странице boost")
            return None

        except Exception as e:
            logger.error(f"Ошибка быстрой проверки ID карты: {e}")
            return None

    def parse_boost_page(self) -> Optional[Dict]:
        """Полный парсинг страницы boost"""
        try:
            r = self.session.get(BOOST_URL, timeout=REQUEST_TIMEOUT)
            if r.status_code != 200:
                logger.warning(f"Ошибка загрузки boost: {r.status_code}")
                return None

            soup = BeautifulSoup(r.text, 'html.parser')

            # 1. ID карты
            link = soup.find('a', href=re.compile(r'/cards/\d+/users'))
            card_id = None
            if link:
                m = re.search(r'/cards/(\d+)/', link.get('href', ''))
                if m:
                    card_id = m.group(1)

            if not card_id:
                logger.warning("Не удалось найти ID карты при полном парсинге")
                return None

            # 2. Картинка карты
            img_tag = soup.find('img', src=re.compile(r'/img/cards/'))
            card_image_url = (BASE_URL + img_tag['src']) if img_tag else None

            # 3. Ранг карты
            card_rank = "?"
            if card_image_url and self.rank_detector and self.rank_detector.is_ready:
                card_rank = self.rank_detector.detect_from_url(
                    card_image_url, session=self.session
                )

            # 4. Замен карты
            card_progress = '?/?'
            change_div = soup.find('div', class_='club-boost__change')
            if change_div:
                inner = change_div.find('div')
                if inner:
                    raw = inner.get_text(separator='', strip=True)
                    card_progress = re.sub(r'\s+', '', raw)

            # 5. Вложено сегодня
            daily_donated = '?/?'
            rules_ul = soup.find('ul', class_='club-boost__rules')
            if rules_ul:
                for li in rules_ul.find_all('li'):
                    m = re.search(r'пожертвовать до\s+(\d+/\d+)\s+карт', li.get_text())
                    if m:
                        daily_donated = m.group(1)
                        break

            # 6. Название карты
            card_name = self._get_card_name(card_id)

            # 7-8. Количества
            wants_count = self._get_count(
                f"{BASE_URL}/cards/{card_id}/offers/want", 'profile__friends-item', per_page=60
            )
            owners_count = self._get_count(
                f"{BASE_URL}/cards/{card_id}/users", 'profile__friends-item', per_page=36
            )

            # 9. Владельцы из клуба
            club_owners = []
            owners_section = soup.find('div', class_='club-boost__owners')
            if owners_section:
                owners_list = owners_section.find('div', class_='club-boost__owners-list')
                if owners_list:
                    for user_div in owners_list.find_all('div', class_='club-boost__user'):
                        a = user_div.find('a', class_='club-boost__avatar')
                        if a:
                            href = a.get('href', '')
                            uid_m = re.search(r'/users/(\d+)', href)
                            if uid_m:
                                profile_id = uid_m.group(1)
                                profile_url = f"{BASE_URL}{href}"
                                
                                from utils.helpers import get_site_nickname
                                nickname = get_site_nickname(profile_url)
                                
                                club_owners.append({
                                    'id': profile_id,
                                    'url': profile_url,
                                    'nickname': nickname or f"User {profile_id}"
                                })

            return {
                'card_id':        card_id,
                'card_name':      card_name,
                'card_rank':      card_rank,
                'card_image_url': card_image_url,
                'card_progress':  card_progress,
                'daily_donated':  daily_donated,
                'wants_count':    wants_count,
                'owners_count':   owners_count,
                'club_owners':    club_owners,
                'timestamp':      datetime.now(),
            }

        except Exception as e:
            logger.error(f"Ошибка полного парсинга boost: {e}", exc_info=True)
            return None

    def _get_card_name(self, card_id: str) -> str:
        """Получает название карты"""
        try:
            r = self.session.get(
                f"{BASE_URL}/cards/{card_id}/offers/want", timeout=REQUEST_TIMEOUT
            )
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                title = soup.find('h2', class_='secondary-title')
                if title:
                    return title.get_text(strip=True).replace(
                        'Пользователям нужна карта ', ''
                    )
        except Exception as e:
            logger.error(f"Ошибка получения названия карты {card_id}: {e}")
        return "Неизвестная карта"

    def _get_count(self, url: str, item_class: str, per_page: int = 60) -> int:
        """Считает элементы по всем страницам"""
        try:
            r = self.session.get(url, timeout=REQUEST_TIMEOUT)
            if r.status_code != 200:
                return 0

            soup = BeautifulSoup(r.text, 'html.parser')
            pages = self._get_page_count(soup)

            if pages == 1:
                return len(soup.find_all('a', class_=item_class))

            last_r = self.session.get(f"{url}?page={pages}", timeout=REQUEST_TIMEOUT)
            if last_r.status_code != 200:
                return (pages - 1) * per_page

            last_soup = BeautifulSoup(last_r.text, 'html.parser')
            return (pages - 1) * per_page + len(last_soup.find_all('a', class_=item_class))

        except Exception as e:
            logger.error(f"Ошибка подсчёта элементов ({url}): {e}")
            return 0

    @staticmethod
    def _get_page_count(soup: BeautifulSoup) -> int:
        """Определяет количество страниц"""
        try:
            pagination = soup.find('ul', class_='pagination')
            if not pagination:
                return 1
            max_page = 1
            for btn in pagination.find_all('li', class_='pagination__button'):
                a = btn.find('a')
                if a and a.get_text(strip=True).isdigit():
                    max_page = max(max_page, int(a.get_text(strip=True)))
            return max_page
        except Exception:
            return 1

    @staticmethod
    def format_caption(data: Dict, is_changed: bool = False) -> str:
        """Подпись к фото карты"""
        header = (
            "🔄 <b>Карта клуба сменилась!</b>"
            if is_changed
            else "🎴 <b>Текущая карта клуба</b>"
        )

        rank = data.get('card_rank', '?')

        if data.get('club_owners'):
            owners_lines = "\n".join(
                "👤 <a href='{}'>{}</a>".format(
                    o['url'], o.get('nickname', 'User ' + str(o['id']))
                )
                for o in data['club_owners']
            )
            club_block = f"Могут внести:\n{owners_lines}"
        else:
            club_block = "Карты нет ни у кого из клуба"

        ts = (
            data['timestamp'].strftime('%d.%m.%Y %H:%M:%S')
            if isinstance(data.get('timestamp'), datetime)
            else "—"
        )

        return (
            f"{header}\n"
            f"<b>{data['card_name']}</b>\n"
            f"ID: {data['card_id']} | Ранг: {rank}\n\n"
            f"👥 Владельцев: {data['owners_count']} | Желающих: {data['wants_count']}\n"
            f"📅 Вложено сегодня: {data['daily_donated']}\n"
            f"🎯 Замен: {data['card_progress']}\n"
            f"{club_block}\n\n"
            f"<a href='{BOOST_URL}'>Внести карту</a>\n"
            f"⏰ {ts}"
        )

    async def send_notification(
        self,
        bot,
        chat_id,
        thread_id: Optional[int],
        data: Dict,
        is_changed: bool = False,
    ):
        """Отправляет ОДНО сообщение: фото карты + подпись"""
        caption = self.format_caption(data, is_changed)

        kwargs = dict(parse_mode=ParseMode.HTML)
        if thread_id:
            kwargs['message_thread_id'] = thread_id

        logger.info(f"📤 Отправка уведомления в chat_id={chat_id}, thread_id={thread_id}")
        logger.debug(f"Подпись: {caption[:100]}...")

        try:
            if data.get('card_image_url'):
                logger.debug(f"Отправка фото: {data['card_image_url']}")
                msg = await bot.send_photo(
                    chat_id=chat_id,
                    photo=data['card_image_url'],
                    caption=caption,
                    **kwargs,
                )
                logger.info(f"✅ Фото отправлено успешно (msg_id={msg.message_id})")
            else:
                logger.warning("⚠️ Нет URL изображения, отправка текстом")
                msg = await bot.send_message(
                    chat_id=chat_id,
                    text=caption,
                    disable_web_page_preview=True,
                    **kwargs,
                )
                logger.info(f"✅ Текст отправлен успешно (msg_id={msg.message_id})")

        except Exception as e:
            logger.error(f"❌ Ошибка отправки в группу (chat_id={chat_id}): {e}", exc_info=True)
            try:
                logger.info("🔄 Попытка fallback отправки текстом")
                msg = await bot.send_message(
                    chat_id=chat_id,
                    text=caption,
                    disable_web_page_preview=True,
                    **kwargs,
                )
                logger.info(f"✅ Fallback успешен (msg_id={msg.message_id})")
            except Exception as e2:
                logger.error(f"❌ Fallback тоже failed: {e2}", exc_info=True)


# ═════════════════════════════════════════════════════════════
# ✅ ИСПРАВЛЕННАЯ ФУНКЦИЯ УВЕДОМЛЕНИЯ ПОЛЬЗОВАТЕЛЕЙ
# ═════════════════════════════════════════════════════════════

async def notify_card_owners(context, card_data: Dict):
    """Уведомляет пользователей бота, у которых есть нужная карта"""
    from database.db import get_all_users
    
    club_owner_ids = {o['id'] for o in card_data.get('club_owners', [])}
    
    if not club_owner_ids:
        logger.debug("📭 Нет владельцев карты в клубе — уведомления не требуются")
        return
    
    logger.info(f"🔍 Проверяем {len(club_owner_ids)} владельцев карты среди пользователей бота")
    
    bot_users = get_all_users()
    logger.debug(f"📊 Всего пользователей бота: {len(bot_users)}")
    
    notified_count = 0
    
    for user in bot_users:
        user_id = user['user_id']
        main_profile_id = user.get('profile_id')
        twinks_json = user.get('twinks')
        
        has_card = False
        card_source = None
        account_nickname = None

        # Проверяем основной аккаунт
        if main_profile_id and main_profile_id in club_owner_ids:
            has_card = True
            account_nickname = user.get('site_nickname') or 'User ' + str(main_profile_id)
            card_source = account_nickname
            logger.info(f"✅ Карта найдена у пользователя {user_id} (основной: {account_nickname})")

        # Проверяем твинов
        if not has_card and twinks_json:
            try:
                twinks = json.loads(twinks_json)
                for twink in twinks:
                    if twink.get('profile_id') in club_owner_ids:
                        has_card = True
                        account_nickname = twink.get('site_nickname') or 'User ' + str(twink.get('profile_id'))
                        card_source = account_nickname
                        logger.info(f"✅ Карта найдена у пользователя {user_id} (твин: {account_nickname})")
                        break
            except Exception as e:
                logger.error(f"❌ Ошибка парсинга твинов для пользователя {user_id}: {e}")

        # Отправляем личное уведомление
        if has_card:
            try:
                caption = (
                    f"🎴 <b>У вас есть нужная карта клуба!</b>\n\n"
                    f"<b>{card_data['card_name']}</b>\n"
                    f"ID: {card_data['card_id']} | Ранг: {card_data.get('card_rank', '?')}\n\n"
                    f"📍 Аккаунт: <b>{account_nickname}</b>\n"
                    f"🎯 Замен: {card_data['card_progress']}\n"
                    f"📅 Вложено сегодня: {card_data['daily_donated']}\n\n"
                    f"<a href='{BOOST_URL}'>🚀 Внести карту в клуб</a>"
                )
                
                logger.debug(f"📤 Отправка личного уведомления пользователю {user_id}")
                
                if card_data.get('card_image_url'):
                    await context.bot.send_photo(
                        chat_id=user_id,
                        photo=card_data['card_image_url'],
                        caption=caption,
                        parse_mode=ParseMode.HTML
                    )
                else:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=caption,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True
                    )
                
                notified_count += 1
                logger.info(f"✅ Личное уведомление отправлено пользователю {user_id} ({card_source})")
                
            except Exception as e:
                logger.error(f"❌ Ошибка отправки уведомления пользователю {user_id}: {e}", exc_info=True)
    
    if notified_count > 0:
        logger.info(f"🎯 Отправлено {notified_count} личных уведомлений о карте {card_data['card_id']}")
    else:
        logger.debug("📭 Пользователей бота с этой картой не найдено")


# ═════════════════════════════════════════════════════════════
# ✅ ИСПРАВЛЕННАЯ ФОНОВАЯ ЗАДАЧА
# ═════════════════════════════════════════════════════════════

async def card_monitoring_job(context):
    """
    Выполняется каждые 2 секунды
    
    ✅ ИСПРАВЛЕНО:
    - Проверка наличия карты в БД ПЕРЕД сохранением
    - TELEGRAM_GROUP_ID конвертируется в int
    - Добавлено детальное логирование
    """
    try:
        if 'card_monitor' not in context.bot_data:
            logger.debug("⏭️ card_monitor не инициализирован, пропускаем")
            return

        monitor: CardMonitor = context.bot_data['card_monitor']

        from config.settings import TELEGRAM_GROUP_ID
        from database.db import save_club_card, is_club_card_saved

        CARD_TOPIC_ID = context.bot_data.get('card_topic_id')
        
        # ✅ Конвертируем TELEGRAM_GROUP_ID в int
        try:
            GROUP_ID = int(TELEGRAM_GROUP_ID)
        except (ValueError, TypeError):
            logger.error(f"❌ Невалидный TELEGRAM_GROUP_ID: {TELEGRAM_GROUP_ID}")
            return

        # ── Шаг 1: быстрая проверка ID ──────────────────────────
        logger.debug("🔍 Быстрая проверка ID карты...")
        current_id = monitor.get_current_card_id()
        
        if not current_id:
            logger.warning("⚠️ Не удалось получить ID карты")
            return

        logger.debug(f"📋 Текущая карта: {current_id}")

        # ── Первый запуск ────────────────────────────────────────
        if not monitor.initialized:
            logger.info("=" * 60)
            logger.info(f"🆕 ПЕРВЫЙ ЗАПУСК: Обработка карты {current_id}")
            logger.info("=" * 60)
            
            monitor.initialized = True
            monitor.last_card_id = current_id

            # ✅ ИСПРАВЛЕНИЕ: Проверяем наличие ПЕРЕД сохранением
            was_in_db = is_club_card_saved(current_id)
            logger.info(f"💾 Карта в БД: {'Да' if was_in_db else 'Нет'}")

            # Полный парсинг
            logger.info("📊 Запуск полного парсинга...")
            data = monitor.parse_boost_page()

            if not data:
                logger.warning("⚠️ Не удалось получить данные карты при первом запуске")
                return

            logger.info(
                f"✅ Данные получены: {data.get('card_name')} "
                f"(ранг {data.get('card_rank')})"
            )

            # Сохраняем в БД
            save_club_card(data)
            context.bot_data['last_card_data'] = data
            logger.info("💾 Карта сохранена в БД")

            # ✅ ИСПРАВЛЕНИЕ: Отправляем ЕСЛИ карты НЕ БЫЛО в БД
            if not was_in_db:
                if CARD_TOPIC_ID:
                    logger.info(f"📤 Отправка уведомления в группу {GROUP_ID}, топик {CARD_TOPIC_ID}")
                    await monitor.send_notification(
                        context.bot, GROUP_ID, CARD_TOPIC_ID,
                        data, is_changed=False
                    )
                else:
                    logger.warning("⚠️ CARD_TOPIC_ID не задан, пропускаем отправку в группу")
            else:
                logger.info("⏭️ Карта уже была в БД, пропускаем уведомление в группу (избегаем дублей)")

            # Уведомляем пользователей
            logger.info("👥 Проверка владельцев среди пользователей бота...")
            await notify_card_owners(context, data)
            
            logger.info("=" * 60)
            logger.info("✅ Первый запуск завершён")
            logger.info("=" * 60)
            return

        # ── Карта не изменилась ──────────────────────────────────
        if current_id == monitor.last_card_id:
            logger.debug(f"⏭️ Карта не изменилась ({current_id}), пропускаем")
            return

        # ── Карта сменилась! ─────────────────────────────────────
        logger.info("=" * 60)
        logger.info(f"🔄 СМЕНА КАРТЫ: {monitor.last_card_id} → {current_id}")
        logger.info("=" * 60)
        
        monitor.last_card_id = current_id

        # Полный парсинг
        logger.info("📊 Запуск полного парсинга новой карты...")
        data = monitor.parse_boost_page()
        
        if not data:
            logger.warning("⚠️ Не удалось получить данные о новой карте")
            return

        logger.info(
            f"✅ Данные получены: {data.get('card_name')} "
            f"(ранг {data.get('card_rank')})"
        )

        # Сохраняем
        save_club_card(data)
        context.bot_data['last_card_data'] = data
        logger.info("💾 Карта сохранена в БД")

        # Отправляем в группу
        if CARD_TOPIC_ID:
            logger.info(f"📤 Отправка уведомления о смене в группу {GROUP_ID}, топик {CARD_TOPIC_ID}")
            await monitor.send_notification(
                context.bot, GROUP_ID, CARD_TOPIC_ID,
                data, is_changed=True
            )
        else:
            logger.warning("⚠️ CARD_TOPIC_ID не задан, пропускаем отправку в группу")

        # Уведомляем пользователей
        logger.info("👥 Проверка владельцев среди пользователей бота...")
        await notify_card_owners(context, data)
        
        logger.info("=" * 60)
        logger.info("✅ Смена карты обработана")
        logger.info("=" * 60)

    except Exception as e:
        logger.error("=" * 60)
        logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА в мониторинге карт: {e}")
        logger.error("=" * 60)
        logger.exception(e)