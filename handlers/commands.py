"""
Обработчики команд пользователей
✅ ИСПРАВЛЕНО: Правильная проверка ролей (оператор vs администратор)
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from config.settings import WELCOME_TEXT, ADMIN_CHAT_ID
from database.db import (
    is_blacklisted, is_user_linked, save_user, get_blacklist, 
    remove_from_blacklist, log_operator_action, get_operator_logs,
    get_operator_stats, get_dialog_messages, get_dialog_stats,
    # ✅ ИСПРАВЛЕНИЕ: Используем правильные функции проверки ролей
    is_staff, is_admin
)
from keyboards.inline import get_main_menu_keyboard, get_reply_keyboard_for_linked_user
from utils.dialog_manager import DialogManager
from utils.helpers import get_user_link

logger = logging.getLogger(__name__)


# ✅ УДАЛЕНА НЕПРАВИЛЬНАЯ ФУНКЦИЯ is_operator()
# Теперь используем is_staff() и is_admin() из database.db


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user

    # Проверка чёрного списка
    if is_blacklisted(user.id):
        await update.message.reply_text(
            "❌ Вы заблокированы и не можете использовать этого бота.\n"
            "Если вы считаете это ошибкой, обратитесь к администратору."
        )
        logger.warning(f"Заблокированный пользователь {user.id} пытается использовать /start")
        return

    # Сохраняем базовую информацию о пользователе
    save_user(user.id, user.username, user.first_name, user.last_name)

    linked = is_user_linked(user.id)
    # ✅ ИСПРАВЛЕНИЕ: Используем is_staff() вместо is_operator()
    is_operator = is_staff(user.id)

    if linked:
        # Привязанный пользователь — показываем клавиатуру (с учетом роли персонала)
        await update.message.reply_text(
            WELCOME_TEXT + "\n\n✅ Ваш аккаунт привязан.\n"
            "Нажмите на иконку с квадратами рядом с полем ввода, чтобы открыть меню 👇",
            reply_markup=get_reply_keyboard_for_linked_user(is_operator=is_operator),
            parse_mode=ParseMode.HTML
        )
    else:
        # Непривязанный — inline-меню
        await update.message.reply_text(
            WELCOME_TEXT,
            reply_markup=get_main_menu_keyboard(),
            parse_mode=ParseMode.HTML
        )

    logger.info(f"Пользователь {user.id} ({user.username}) запустил бота, linked={linked}, staff={is_operator}")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отменяет текущее действие"""
    context.user_data['state'] = None
    context.user_data['reply_to_user'] = None
    context.user_data['blocking_user_id'] = None
    await update.message.reply_text("✅ Отменено")


async def blacklist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показывает список заблокированных пользователей
    Команда: /blacklist (только для персонала)
    """
    user_id = update.effective_user.id
    
    # ✅ ИСПРАВЛЕНИЕ: Проверяем, является ли пользователь персоналом
    if not is_staff(user_id):
        return
    
    # ✅ Логируем действие
    log_operator_action(user_id, 'blacklist_view')
    
    blacklist = get_blacklist()
    
    if not blacklist:
        await update.message.reply_text(
            "📋 <b>Чёрный список</b>\n\n"
            "Чёрный список пуст.",
            parse_mode=ParseMode.HTML
        )
        return
    
    text = f"📋 <b>Чёрный список ({len(blacklist)} польз.)</b>\n\n"
    
    for bl_uid, username, first_name, reason, blocked_at in blacklist:
        ul = get_user_link(bl_uid, first_name or username or f"User {bl_uid}")
        text += (
            f"👤 {ul}\n"
            f"   ID: <code>{bl_uid}</code>\n"
        )
        if username:
            text += f"   Username: @{username}\n"
        if reason:
            text += f"   📝 Причина: {reason}\n"
        text += f"   🕐 Заблокирован: {blocked_at}\n"
        text += f"   ✅ Разблокировать: /unblock {bl_uid}\n"
        text += "   ─────────────────────\n\n"
    
    text += "💡 Для разблокировки используйте:\n<code>/unblock USERID</code>"
    
    # Отправляем с кнопками разблокировки для последних 5 пользователей
    keyboard = []
    for bl_uid, username, first_name, reason, blocked_at in blacklist[:5]:
        name = first_name or username or f"User {bl_uid}"
        keyboard.append([
            InlineKeyboardButton(
                f"✅ Разблокировать {name}",
                callback_data=f'unblock_{bl_uid}'
            )
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )


async def unblock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Разблокирует пользователя по ID
    Команда: /unblock USERID или /unblock_USERID (для обратной совместимости)
    """
    user_id = update.effective_user.id
    
    # ✅ ИСПРАВЛЕНИЕ: Проверяем, является ли пользователь персоналом
    if not is_staff(user_id):
        return
    
    # Извлекаем ID пользователя из команды
    command_text = update.message.text.strip()
    target_user_id = None
    
    # Вариант 1: /unblock 123456789 (с пробелом)
    if context.args and len(context.args) > 0:
        try:
            target_user_id = int(context.args[0])
        except ValueError:
            pass
    
    # Вариант 2: /unblock_123456789 (со подчеркиванием)
    if target_user_id is None and '_' in command_text:
        try:
            target_user_id = int(command_text.split('_', 1)[1])
        except (IndexError, ValueError):
            pass
    
    # Если ID не удалось извлечь
    if target_user_id is None:
        await update.message.reply_text(
            "❌ <b>Неверный формат команды</b>\n\n"
            "Используйте один из форматов:\n"
            "• <code>/unblock USERID</code> (рекомендуется)\n"
            "• <code>/unblock_USERID</code>\n\n"
            "Примеры:\n"
            "• <code>/unblock 123456789</code>\n"
            "• <code>/unblock_123456789</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Проверяем, заблокирован ли пользователь
    if not is_blacklisted(target_user_id):
        await update.message.reply_text(
            f"ℹ️ Пользователь <code>{target_user_id}</code> не заблокирован",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Получаем информацию о пользователе для логирования
    from database.db import get_user_info
    user_info = get_user_info(target_user_id)
    target_username = user_info[1] if user_info else None
    target_first_name = user_info[2] if user_info else None
    
    # Разблокируем
    remove_from_blacklist(target_user_id)
    
    # ✅ Логируем действие
    log_operator_action(
        user_id, 
        'user_unblocked',
        target_user_id=target_user_id,
        target_username=target_username,
        target_first_name=target_first_name
    )
    
    await update.message.reply_text(
        f"✅ <b>Пользователь разблокирован</b>\n\n"
        f"ID: <code>{target_user_id}</code>",
        parse_mode=ParseMode.HTML
    )
    
    logger.info(f"Персонал {user_id} разблокировал пользователя {target_user_id}")


async def dialogs_command_impl(bot_data: dict, bot, operator_id: int, chat_id: int):
    """Внутренняя реализация команды /dialogs"""
    # ✅ Логируем действие
    log_operator_action(operator_id, 'dialogs_view')
    
    dm = DialogManager(bot_data)
    dialogs = dm.get_all_operator_dialogs(operator_id)
    
    if not dialogs:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "📭 <b>У вас нет активных диалогов</b>\n\n"
                "Чтобы начать диалог, нажмите кнопку «Ответить» "
                "под сообщением от пользователя."
            ),
            parse_mode=ParseMode.HTML
        )
        return
    
    # Получаем текущий активный диалог
    active_dialog_id = dm.get_active_dialog_for_operator(operator_id)
    
    # Формируем сообщение со списком диалогов
    text = f"💬 <b>Ваши активные диалоги ({len(dialogs)})</b>\n\n"
    
    keyboard = []
    for idx, (dialog_id, info) in enumerate(dialogs, 1):
        is_active = (dialog_id == active_dialog_id)
        status_emoji = "🟢" if is_active else "⚪️"
        
        user_name = info['user_name']
        user_id_str = info['user_id']
        msg_count = info['messages_count']
        last_msg = info['last_message_at']
        
        text += (
            f"{status_emoji} <b>{idx}. {user_name}</b>\n"
            f"   ID: <code>{user_id_str}</code>\n"
            f"   Сообщений: {msg_count}\n"
            f"   Последнее: {last_msg}\n"
        )
        
        if is_active:
            text += "   <i>← Текущий диалог</i>\n"
        
        text += "\n"
        
        # Добавляем кнопку для переключения (если это не текущий диалог)
        if not is_active:
            keyboard.append([
                InlineKeyboardButton(
                    f"Переключиться на {user_name}",
                    callback_data=f"switch_dialog_{dialog_id}"
                )
            ])
    
    text += (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <b>Команды:</b>\n"
        "• /end_dialog — завершить текущий диалог\n"
        "• /end_all — завершить все диалоги\n"
        "• /dialogs — обновить список"
    )
    
    # Добавляем кнопку "Завершить все"
    if len(dialogs) > 1:
        keyboard.append([
            InlineKeyboardButton("🚫 Завершить все диалоги", callback_data="end_all_dialogs")
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )


async def dialogs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показывает список всех активных диалогов персонала
    Команда: /dialogs
    """
    user_id = update.effective_user.id
    
    # ✅ ИСПРАВЛЕНИЕ: Проверяем, является ли пользователь персоналом
    if not is_staff(user_id):
        return
    
    await dialogs_command_impl(context.bot_data, context.bot, user_id, update.effective_chat.id)


async def end_dialog_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершает текущий активный диалог"""
    user_id = update.effective_user.id
    dm = DialogManager(context.bot_data)
    
    # ✅ ИСПРАВЛЕНИЕ: Используем is_staff() вместо is_operator()
    is_operator = is_staff(user_id)
    
    if is_operator:
        active_dialog_id = dm.get_active_dialog_for_operator(user_id)
        
        if not active_dialog_id:
            await update.message.reply_text(
                "ℹ️ У вас нет активного диалога\n\n"
                "Используйте /dialogs чтобы увидеть все диалоги",
                parse_mode=ParseMode.HTML
            )
            return
        
        dialog_info = dm.get_dialog_info(active_dialog_id)
        other_user_id = dialog_info['user_id']
        other_user_name = dialog_info['user_name']
        
        # ✅ Логируем действие
        log_operator_action(
            user_id,
            'dialog_end',
            target_user_id=other_user_id,
            target_first_name=other_user_name,
            details=f"dialog_id: {active_dialog_id}"
        )
        
        # Завершаем диалог
        dm.end_dialog(active_dialog_id)
        
        remaining_count = dm.get_dialogs_count(user_id)
        
        await update.message.reply_text(
            f"✅ <b>Диалог с {other_user_name} завершен</b>\n\n"
            + (f"У вас осталось активных диалогов: {remaining_count}\n"
               f"Используйте /dialogs для просмотра" if remaining_count > 0
               else "У вас больше нет активных диалогов"),
            parse_mode=ParseMode.HTML
        )
        
        # Уведомляем пользователя
        try:
            await context.bot.send_message(
                chat_id=other_user_id,
                text=(
                    "✅ <b>Диалог завершен</b>\n\n"
                    "Оператор завершил диалог с вами."
                ),
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Ошибка уведомления пользователя {other_user_id}: {e}")
    
    else:
        dialog_id, dialog_info = dm.find_user_dialog(user_id)
        
        if not dialog_id:
            await update.message.reply_text(
                "ℹ️ У вас нет активного диалога",
                parse_mode=ParseMode.HTML
            )
            return
        
        operator_id = dialog_info['operator_id']
        
        dm.end_dialog(dialog_id)
        
        await update.message.reply_text(
            "✅ <b>Диалог завершен</b>\n\n"
            "Вы больше не в режиме диалога с оператором.",
            parse_mode=ParseMode.HTML
        )
        
        try:
            await context.bot.send_message(
                chat_id=operator_id,
                text=(
                    f"✅ <b>Диалог завершен</b>\n\n"
                    f"Пользователь <a href='tg://user?id={user_id}'>{update.effective_user.first_name}</a> "
                    f"завершил диалог.\n\n"
                    f"Используйте /dialogs для просмотра оставшихся диалогов"
                ),
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Ошибка уведомления персонала {operator_id}: {e}")


async def end_all_dialogs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершает ВСЕ активные диалоги персонала"""
    user_id = update.effective_user.id
    
    # ✅ ИСПРАВЛЕНИЕ: Проверяем, является ли пользователь персоналом
    if not is_staff(user_id):
        return
    
    dm = DialogManager(context.bot_data)
    dialogs = dm.get_all_operator_dialogs(user_id)
    
    if not dialogs:
        await update.message.reply_text(
            "ℹ️ У вас нет активных диалогов",
            parse_mode=ParseMode.HTML
        )
        return
    
    user_ids = [info['user_id'] for _, info in dialogs]
    
    # ✅ Логируем действие
    log_operator_action(
        user_id,
        'dialog_end',
        details=f"Завершено диалогов: {len(dialogs)}"
    )
    
    count = dm.end_all_operator_dialogs(user_id)
    
    await update.message.reply_text(
        f"✅ <b>Завершено диалогов: {count}</b>\n\n"
        f"Все активные диалоги закрыты.",
        parse_mode=ParseMode.HTML
    )
    
    for other_user_id in user_ids:
        try:
            await context.bot.send_message(
                chat_id=other_user_id,
                text=(
                    "✅ <b>Диалог завершен</b>\n\n"
                    "Оператор завершил диалог с вами."
                ),
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Ошибка уведомления пользователя {other_user_id}: {e}")


# ══════════════════════════════════════════════════════════════
# ✅ КОМАНДЫ ПРОСМОТРА ЛОГОВ
# ══════════════════════════════════════════════════════════════

async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показывает логи действий персонала
    Команда: /logs [количество] [тип]
    """
    user_id = update.effective_user.id
    
    # ✅ ИСПРАВЛЕНИЕ: Проверяем, является ли пользователь персоналом
    if not is_staff(user_id):
        return
    
    # Парсим аргументы
    limit = 20
    action_type = None
    
    if context.args:
        for arg in context.args:
            if arg.isdigit():
                limit = min(int(arg), 100)  # Максимум 100
            else:
                action_type = arg
    
    # Получаем логи
    logs = get_operator_logs(
        operator_id=user_id,
        action_type=action_type,
        limit=limit
    )
    
    if not logs:
        await update.message.reply_text(
            "📋 <b>Логи действий</b>\n\n"
            "Логи отсутствуют.",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Формируем сообщение
    action_names = {
        'dialog_start': '🟢 Начало диалога',
        'dialog_end': '🔴 Завершение диалога',
        'dialog_switch': '🔄 Переключение диалога',
        'user_blocked': '🚫 Блокировка',
        'user_unblocked': '✅ Разблокировка',
        'blacklist_view': '📋 Просмотр ЧС',
        'dialogs_view': '💬 Просмотр диалогов',
        'message_sent': '📨 Сообщение'
    }
    
    header = f"📋 <b>Логи действий ({len(logs)})</b>\n"
    if action_type:
        header += f"Фильтр: {action_names.get(action_type, action_type)}\n"
    header += "\n"
    
    text = header
    
    for log in logs[:20]:  # Показываем только первые 20 в сообщении
        log_id, op_id, action, target_id, target_user, target_name, details, created = log
        
        action_icon = action_names.get(action, action)
        
        text += f"{action_icon}\n"
        
        if target_id:
            user_link = get_user_link(target_id, target_name or target_user or f"User {target_id}")
            text += f"   Пользователь: {user_link}\n"
        
        if details:
            text += f"   Детали: {details}\n"
        
        text += f"   Время: {created}\n"
        text += "   ─────────────\n\n"
    
    if len(logs) > 20:
        text += f"\n💡 Показаны первые 20 из {len(logs)} записей"
    
    text += (
        "\n━━━━━━━━━━━━━━━━━━━━\n"
        "Команды:\n"
        "• /logs - последние 20\n"
        "• /logs 50 - последние 50\n"
        "• /logs dialog_start - только диалоги\n"
        "• /stats - статистика"
    )
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показывает статистику действий персонала
    Команда: /stats
    """
    user_id = update.effective_user.id
    
    # ✅ ИСПРАВЛЕНИЕ: Проверяем, является ли пользователь персоналом
    if not is_staff(user_id):
        return
    
    # Получаем статистику
    stats = get_operator_stats(user_id)
    
    text = (
        f"📊 <b>Статистика персонала</b>\n\n"
        f"Всего действий: {stats['total_actions']}\n"
        f"Диалогов начато: {stats['total_dialogs']}\n"
        f"Блокировок: {stats['total_blocks']}\n"
    )
    
    if stats['first_action']:
        text += f"\nПервое действие: {stats['first_action']}\n"
    
    if stats['actions_by_type']:
        text += "\n<b>По типам:</b>\n"
        action_names = {
            'dialog_start': 'Начало диалогов',
            'dialog_end': 'Завершение диалогов',
            'dialog_switch': 'Переключения',
            'user_blocked': 'Блокировки',
            'user_unblocked': 'Разблокировки',
            'blacklist_view': 'Просмотр ЧС',
            'dialogs_view': 'Просмотр диалогов',
            'message_sent': 'Сообщения'
        }
        
        for action_type, count in sorted(
            stats['actions_by_type'].items(), 
            key=lambda x: x[1], 
            reverse=True
        ):
            name = action_names.get(action_type, action_type)
            text += f"• {name}: {count}\n"
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def dialog_history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показывает историю сообщений конкретного диалога
    Команда: /history [dialog_id]
    """
    user_id = update.effective_user.id
    
    # ✅ ИСПРАВЛЕНИЕ: Проверяем, является ли пользователь персоналом
    if not is_staff(user_id):
        return
    
    if not context.args:
        await update.message.reply_text(
            "❌ <b>Укажите ID диалога</b>\n\n"
            "Формат: <code>/history dialog_ID1_ID2</code>\n\n"
            "Пример: <code>/history dialog_990623973_123456</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    dialog_id = context.args[0]
    
    # Получаем сообщения
    messages = get_dialog_messages(dialog_id, limit=50)
    
    if not messages:
        await update.message.reply_text(
            f"ℹ️ История диалога <code>{dialog_id}</code> не найдена",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Получаем статистику
    stats = get_dialog_stats(dialog_id)
    
    text = (
        f"💬 <b>История диалога</b>\n"
        f"ID: <code>{dialog_id}</code>\n\n"
        f"Всего сообщений: {stats['total_messages']}\n"
        f"От персонала: {stats['operator_messages']}\n"
        f"От пользователя: {stats['user_messages']}\n"
        f"Период: {stats['first_message']} - {stats['last_message']}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    for msg in messages[:30]:  # Показываем последние 30
        msg_id, dlg_id, sender_id, sender_type, msg_text, created = msg
        
        icon = "👤" if sender_type == "operator" else "💬"
        sender_label = "Персонал" if sender_type == "operator" else "Пользователь"
        
        # Обрезаем длинные сообщения
        display_text = msg_text[:100] + "..." if len(msg_text) > 100 else msg_text
        
        text += (
            f"{icon} <b>{sender_label}</b> ({created})\n"
            f"{display_text}\n\n"
        )
    
    if len(messages) > 30:
        text += f"\n💡 Показаны последние 30 из {len(messages)} сообщений"
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)