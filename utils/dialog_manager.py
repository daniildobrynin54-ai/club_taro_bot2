"""
Менеджер диалогов - управление множественными одновременными диалогами
"""
import logging
from datetime import datetime
from typing import Optional, List, Dict, Tuple

logger = logging.getLogger(__name__)


class DialogManager:
    """Управление множественными диалогами между оператором и пользователями"""
    
    def __init__(self, bot_data: dict):
        """
        Инициализация менеджера диалогов
        
        Структура данных:
        bot_data['dialogs'] = {
            'dialog_123': {
                'operator_id': 990623973,
                'user_id': 12345,
                'user_name': 'John',
                'started_at': '2024-02-10 15:30:00',
                'last_message_at': '2024-02-10 15:35:00',
                'messages_count': 5
            }
        }
        bot_data['operator_active_dialog'] = {
            990623973: 'dialog_123'  # текущий активный диалог оператора
        }
        """
        self.bot_data = bot_data
        
        if 'dialogs' not in bot_data:
            bot_data['dialogs'] = {}
        
        if 'operator_active_dialog' not in bot_data:
            bot_data['operator_active_dialog'] = {}
    
    def _generate_dialog_id(self, operator_id: int, user_id: int) -> str:
        """Генерирует уникальный ID диалога"""
        return f"dialog_{operator_id}_{user_id}"
    
    def start_dialog(self, operator_id: int, user_id: int, user_name: str = None) -> str:
        """
        Начинает новый диалог или возобновляет существующий
        Возвращает ID диалога
        """
        dialog_id = self._generate_dialog_id(operator_id, user_id)
        
        if dialog_id in self.bot_data['dialogs']:
            # Диалог уже существует - делаем его активным
            logger.info(f"Возобновление существующего диалога {dialog_id}")
            self.bot_data['operator_active_dialog'][operator_id] = dialog_id
            self.bot_data['dialogs'][dialog_id]['last_message_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            return dialog_id
        
        # Создаем новый диалог
        self.bot_data['dialogs'][dialog_id] = {
            'operator_id': operator_id,
            'user_id': user_id,
            'user_name': user_name or f"User {user_id}",
            'started_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'last_message_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'messages_count': 0
        }
        
        # Делаем этот диалог активным для оператора
        self.bot_data['operator_active_dialog'][operator_id] = dialog_id
        
        logger.info(f"Создан новый диалог {dialog_id}: оператор {operator_id} <-> пользователь {user_id}")
        return dialog_id
    
    def get_active_dialog_for_operator(self, operator_id: int) -> Optional[str]:
        """Возвращает ID текущего активного диалога оператора"""
        return self.bot_data['operator_active_dialog'].get(operator_id)
    
    def get_dialog_info(self, dialog_id: str) -> Optional[Dict]:
        """Возвращает информацию о диалоге"""
        return self.bot_data['dialogs'].get(dialog_id)
    
    def get_user_dialog_with_operator(self, user_id: int, operator_id: int) -> Optional[str]:
        """Находит диалог между конкретным пользователем и оператором"""
        dialog_id = self._generate_dialog_id(operator_id, user_id)
        if dialog_id in self.bot_data['dialogs']:
            return dialog_id
        return None
    
    def get_all_operator_dialogs(self, operator_id: int) -> List[Tuple[str, Dict]]:
        """
        Возвращает список всех активных диалогов оператора
        [(dialog_id, dialog_info), ...]
        """
        dialogs = []
        for dialog_id, info in self.bot_data['dialogs'].items():
            if info['operator_id'] == operator_id:
                dialogs.append((dialog_id, info))
        
        # Сортируем по времени последнего сообщения (новые первые)
        dialogs.sort(key=lambda x: x[1]['last_message_at'], reverse=True)
        return dialogs
    
    def switch_dialog(self, operator_id: int, dialog_id: str) -> bool:
        """
        Переключает оператора на другой диалог
        Возвращает True если успешно, False если диалог не найден
        """
        if dialog_id not in self.bot_data['dialogs']:
            logger.warning(f"Попытка переключения на несуществующий диалог {dialog_id}")
            return False
        
        dialog_info = self.bot_data['dialogs'][dialog_id]
        if dialog_info['operator_id'] != operator_id:
            logger.warning(f"Оператор {operator_id} пытается переключиться на чужой диалог {dialog_id}")
            return False
        
        self.bot_data['operator_active_dialog'][operator_id] = dialog_id
        logger.info(f"Оператор {operator_id} переключился на диалог {dialog_id}")
        return True
    
    def end_dialog(self, dialog_id: str) -> Tuple[Optional[int], Optional[int]]:
        """
        Завершает диалог
        Возвращает (operator_id, user_id) или (None, None) если диалог не найден
        """
        if dialog_id not in self.bot_data['dialogs']:
            return None, None
        
        dialog_info = self.bot_data['dialogs'][dialog_id]
        operator_id = dialog_info['operator_id']
        user_id = dialog_info['user_id']
        
        # Удаляем диалог
        del self.bot_data['dialogs'][dialog_id]
        
        # Если это был активный диалог оператора - сбрасываем
        if self.bot_data['operator_active_dialog'].get(operator_id) == dialog_id:
            del self.bot_data['operator_active_dialog'][operator_id]
        
        logger.info(f"Диалог {dialog_id} завершен")
        return operator_id, user_id
    
    def end_all_operator_dialogs(self, operator_id: int) -> int:
        """
        Завершает все диалоги оператора
        Возвращает количество завершенных диалогов
        """
        dialogs_to_end = [
            dialog_id for dialog_id, info in self.bot_data['dialogs'].items()
            if info['operator_id'] == operator_id
        ]
        
        for dialog_id in dialogs_to_end:
            del self.bot_data['dialogs'][dialog_id]
        
        if operator_id in self.bot_data['operator_active_dialog']:
            del self.bot_data['operator_active_dialog'][operator_id]
        
        count = len(dialogs_to_end)
        if count > 0:
            logger.info(f"Завершено {count} диалогов оператора {operator_id}")
        
        return count
    
    def increment_message_count(self, dialog_id: str):
        """Увеличивает счетчик сообщений в диалоге"""
        if dialog_id in self.bot_data['dialogs']:
            self.bot_data['dialogs'][dialog_id]['messages_count'] += 1
            self.bot_data['dialogs'][dialog_id]['last_message_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    def find_user_dialog(self, user_id: int) -> Optional[Tuple[str, Dict]]:
        """
        Находит активный диалог пользователя с любым оператором
        Возвращает (dialog_id, dialog_info) или (None, None)
        """
        for dialog_id, info in self.bot_data['dialogs'].items():
            if info['user_id'] == user_id:
                return dialog_id, info
        return None, None
    
    def get_dialogs_count(self, operator_id: int) -> int:
        """Возвращает количество активных диалогов оператора"""
        return len([d for d in self.bot_data['dialogs'].values() if d['operator_id'] == operator_id])