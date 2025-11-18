# core/firebase_service.py
import logging
from datetime import datetime
from pathlib import Path
import random
from typing import List, Dict

import firebase_admin
from firebase_admin import credentials, firestore, storage
from PyQt6.QtWidgets import QMessageBox

# !!! НОВЫЙ ИМПОРТ ДЛЯ ИСПРАВЛЕНИЯ ПРЕДУПРЕЖДЕНИЯ !!!
# Требуется FieldFilter для использования современного синтаксиса фильтрации.
from google.cloud.firestore import FieldFilter 

from config import CRED_PATH, FIREBASE_STORAGE_BUCKET, DEFAULT_GUIDE_CONTENT
from core.signals import FirebaseSignals
from utils.helpers import hash_password

db = None

listener_running = False

def init_firebase():
    """Инициализирует клиент Firebase/Firestore и Storage."""
    global db
    if not CRED_PATH.exists():
        logging.error(f"Файл учетных данных Firebase не найден: {CRED_PATH.name}")
        QMessageBox.critical(None, "Ошибка Firebase", f"Файл {CRED_PATH.name} не найден. Невозможно подключиться к облаку.")
        return None
    
    if not firebase_admin._apps:
        try:
            cred = credentials.Certificate(CRED_PATH)
            firebase_admin.initialize_app(cred, {
                'storageBucket': FIREBASE_STORAGE_BUCKET.replace("gs://", "")
            })
            db = firestore.client()
            return db
        except Exception as e:
            logging.error(f"Ошибка инициализации Firebase: {e}")
            QMessageBox.critical(None, "Ошибка Firebase", f"Не удалось подключиться к Firebase. Проверьте {CRED_PATH.name} и подключение к сети.\nОшибка: {e}")
            return None
    return db

def upload_image_to_storage(local_path: Path, guide_doc_id: str) -> str | None:
    """Загружает изображение в Firebase Storage и возвращает публичный URL."""
    if not storage:
        logging.error("Firebase Storage не инициализирован.")
        return None
        
    try:
        # Используем guide_doc_id для пути
        storage_path = f"guides/{guide_doc_id}/images/{local_path.name}"
        bucket = storage.bucket()
        blob = bucket.blob(storage_path)
        
        blob.upload_from_filename(str(local_path))
        blob.make_public()
        
        return blob.public_url
    except Exception as e:
        logging.error(f"Ошибка загрузки изображения {local_path.name} в Storage: {e}")
        return None

def generate_unique_id() -> str:
    """Генерирует уникальный, но простой ID для документа контента."""
    return datetime.now().strftime("%Y%m%d%H%M%S") + str(random.randint(100, 999)) 

def ensure_initial_guides():
    """Создает начального админа и базовую структуру гайдов в Firestore."""
    if not db: return
    
    batch = db.batch()
    
    # 1. Администратор (без изменений)
    admin_login = "admin"
    admin_password_hash = hash_password("admin")
    user_ref = db.collection('users').document(admin_login)
    if not user_ref.get().exists:
        batch.set(user_ref, {
            'password_hash': admin_password_hash,
            'role': 'admin'
        })

    # 2. Начальная структура и контент
    structure_ref = db.collection('structure')
    guides_ref = db.collection('guides')

    # Идентификаторы для базового контента
    content_ids = {
        'root_info': 'info_content_id',
        'root_settings': 'settings_content_id',
    }

    initial_content = {
        content_ids['root_info']: {
            "title": "Добро пожаловать!", 
            "content": "# Добро пожаловать...\n\nТекст приветствия."
        },
        content_ids['root_settings']: {
            "title": "Настройка CS2", 
            "content": "# Настройка CS2\n\nОсновные настройки и конфиги."
        },
    }
    
    # Создание контента
    for content_id, data in initial_content.items():
        content_doc = guides_ref.document(content_id)
        if not content_doc.get().exists:
            batch.set(content_doc, data | {'last_modified': datetime.now().isoformat()})

    # Создание узлов структуры
    initial_structure = [
        {'id': 'root_info', 'name': 'Добро пожаловать!', 'parent_id': None, 'type': 'guide', 'guide_doc_id': content_ids['root_info'], 'order': 10},
        {'id': 'folder_maps', 'name': 'Гайды по картам', 'parent_id': None, 'type': 'folder', 'guide_doc_id': None, 'order': 20},
        {'id': 'root_settings', 'name': 'Настройка CS2', 'parent_id': None, 'type': 'guide', 'guide_doc_id': content_ids['root_settings'], 'order': 30},
    ]

    for node in initial_structure:
        node_doc = structure_ref.document(node['id'])
        if not node_doc.get().exists:
            batch.set(node_doc, {
                'name': node['name'], 
                'parent_id': node['parent_id'], 
                'type': node['type'], 
                'guide_doc_id': node['guide_doc_id'],
                'order': node['order']
            })

    if batch._write_pbs: 
        batch.commit()
        logging.info("Пакетная запись начальных данных успешно выполнена.")

# ==================== ФУНКЦИИ УПРАВЛЕНИЯ СТРУКТУРОЙ ====================

def get_structure_metadata():
    """Возвращает все узлы структуры (папки и гайды) для построения дерева."""
    global db
    try:
        # Загружаем узлы, отсортированные для удобства построения дерева
        nodes = db.collection('structure').order_by('parent_id').order_by('order').stream()
        return [doc.to_dict() | {'id': doc.id} for doc in nodes]
    except Exception as e:
        logging.error(f"Ошибка получения структуры гайдов: {e}")
        return []

def create_new_node(name: str, parent_id: str | None, node_type: str, guide_content: str | None = None) -> str | None:
    """Создает новый узел структуры (папку или гайд) и контент для гайда."""
    global db
    try:
        # 1. Определяем следующий номер порядка
        # 🚀 ИСПРАВЛЕНО: Заменили позиционные аргументы в .where() на filter=FieldFilter
        parent_filter = db.collection('structure').where(filter=FieldFilter('parent_id', '==', parent_id)).order_by('order', direction=firestore.Query.DESCENDING).limit(1).get()
        max_order = parent_filter[0].to_dict().get('order', 0) if parent_filter else 0
        new_order = max_order + 10
        
        guide_doc_id = None
        
        # 2. Если это гайд, создаем контент-документ
        if node_type == 'guide':
            guide_doc_id = generate_unique_id()
            guides_ref = db.collection('guides').document(guide_doc_id)
            guides_ref.set({
                'title': name,
                'content': guide_content or DEFAULT_GUIDE_CONTENT(name),
                'last_modified': datetime.now().isoformat()
            })
            
        # 3. Создаем узел структуры
        node_ref = db.collection('structure').document() 
        node_data = {
            'name': name,
            'parent_id': parent_id,
            'type': node_type,
            'order': new_order,
            'guide_doc_id': guide_doc_id
        }
        
        node_ref.set(node_data)
        return node_ref.id
    except Exception as e:
        logging.error(f"Ошибка создания нового узла: {e}")
        return None

def rename_node(node_id: str, new_name: str) -> bool:
    """Переименовывает узел структуры и связанный с ним документ контента (если это гайд)."""
    if not db: return False
    try:
        node_ref = db.collection('structure').document(node_id)
        node_data = node_ref.get().to_dict()
        
        node_ref.update({'name': new_name})
        
        if node_data and node_data.get('type') == 'guide':
            guide_doc_id = node_data.get('guide_doc_id')
            if guide_doc_id:
                db.collection('guides').document(guide_doc_id).update({'title': new_name})
        
        return True
    except Exception as e:
        logging.error(f"Ошибка переименования узла {node_id}: {e}")
        return False
        
def delete_node_recursively(node_id: str) -> bool:
    """Рекурсивно удаляет узел структуры, все его дочерние элементы и связанные документы контента."""
    if not db: return False
    try:
        batch = db.batch()
        
        def get_descendants(parent_id):
            descendants = []
            queue = [parent_id]
            
            # Simple BFS to find all children recursively
            while queue:
                current_id = queue.pop(0)
                descendants.append(current_id)
                # 🚀 ИСПРАВЛЕНО: Заменили позиционные аргументы в .where() на filter=FieldFilter
                children = db.collection('structure').where(filter=FieldFilter('parent_id', '==', current_id)).stream() 
                for child in children:
                    queue.append(child.id)
            return descendants

        all_nodes_to_delete = get_descendants(node_id)
        
        for delete_id in all_nodes_to_delete:
            structure_doc = db.collection('structure').document(delete_id).get()
            if structure_doc.exists:
                structure_data = structure_doc.to_dict()
                
                # Если это гайд, удаляем контент
                if structure_data.get('type') == 'guide':
                    guide_doc_id = structure_data.get('guide_doc_id')
                    if guide_doc_id:
                        batch.delete(db.collection('guides').document(guide_doc_id))
                        
                # Удаляем узел структуры
                batch.delete(db.collection('structure').document(delete_id))
        
        batch.commit()
        return True
    except Exception as e:
        logging.error(f"Ошибка удаления узла {node_id} рекурсивно: {e}")
        return False

# ==================== ФУНКЦИИ КОНТЕНТА ====================

def get_guide_content_firestore_by_structure_id(structure_id: str) -> dict | None: 
    """Получает контент гайда по ID узла структуры."""
    if not db: return None
    try:
        node = db.collection('structure').document(structure_id).get().to_dict()
        if not node or node.get('type') != 'guide':
            return None
        
        guide_doc_id = node.get('guide_doc_id')
        if not guide_doc_id: return None
            
        doc = db.collection('guides').document(guide_doc_id).get()
        return doc.to_dict() if doc.exists else None
    except Exception as e:
        logging.error(f"Ошибка получения контента для ID структуры {structure_id}: {e}")
        return None
        
def save_guide_content_by_structure_id(structure_id: str, content: str) -> bool: 
    """Сохраняет контент гайда по ID узла структуры."""
    if not db: return False
    try:
        node = db.collection('structure').document(structure_id).get().to_dict()
        if not node or node.get('type') != 'guide': return False
            
        guide_doc_id = node.get('guide_doc_id')
        if not guide_doc_id: return False

        now = datetime.now().isoformat()
        guide_ref = db.collection('guides').document(guide_doc_id)
        
        guide_ref.update({
            'content': content,
            'last_modified': now
        })
        return True
    except Exception as e:
        logging.error(f"Ошибка сохранения контента для ID структуры {structure_id}: {e}")
        return False
        
def get_all_guides_for_search_new():
    """Загружает все гайды для локального поиска, используя ID структуры в качестве ключа."""
    if not db: return {}
    try:
        guides = db.collection('guides').stream()
        content_map = {doc.id: doc.to_dict() for doc in guides}
        
        # 🚀 ИСПРАВЛЕНО: Заменили позиционные аргументы в .where() на filter=FieldFilter
        structure = db.collection('structure').where(filter=FieldFilter('type', '==', 'guide')).stream()
        search_data = {}
        for node in structure:
            data = node.to_dict()
            guide_doc_id = data.get('guide_doc_id')
            content = content_map.get(guide_doc_id)
            if content:
                # Используем structure ID как ключ для поиска
                search_data[node.id] = { 
                    'title': data.get('name', 'N/A'),
                    'content': content.get('content', '')
                }
        return search_data
    except Exception as e:
        logging.error(f"Ошибка получения всего контента для поиска: {e}")
        return {}

# ==================== ФУНКЦИИ ПОЛЬЗОВАТЕЛЕЙ (CRUD) ====================
def get_user_role_firestore(login: str, password_hash: str) -> str | None:
    if not db: return None
    try:
        doc = db.collection('users').document(login).get()
        if doc.exists:
            data = doc.to_dict()
            if data.get('password_hash') == password_hash:
                return data.get('role', 'user')
            else:
                return 'Неверный_пароль'
        return 'Пользователя_не_существует'
    except Exception as e:
        logging.error(f"Ошибка аутентификации в Firestore: {e}")
        return None

def register_user_firestore(login: str, password_hash: str) -> bool:
    if not db: return False
    try:
        user_ref = db.collection('users').document(login)
        if user_ref.get().exists:
            return False # Логин занят
            
        user_ref.set({
            'password_hash': password_hash,
            'role': 'user'
        })
        return True
    except Exception as e:
        logging.error(f"Ошибка регистрации в Firestore: {e}")
        return False

def get_all_users_firestore():
    """
    [ИСПРАВЛЕНО] Получает всех пользователей из коллекции 'users'.
    Возвращает словарь: {login: user_data_dict}.
    """
    if not db: return {}
    try:
        users = db.collection('users').stream()
        
        # 🚀 ИСПРАВЛЕНИЕ: Создаем словарь {login: user_data_dict}
        users_dict = {}
        for doc in users:
            login = doc.id
            data = doc.to_dict()
            # Убеждаемся, что роль присутствует
            data['role'] = data.get('role', 'user') 
            users_dict[login] = data
            
        return users_dict
        
    except Exception as e:
        logging.error(f"Ошибка получения списка пользователей: {e}")
        return {}

def set_user_role_firestore(login: str, new_role: str) -> bool:
    if not db: return False
    try:
        db.collection('users').document(login).update({'role': new_role})
        return True
    except Exception as e:
        logging.error(f"Ошибка смены роли в Firestore: {e}")
        return False
#=====================
def update_node_metadata(node_id: str, data: dict) -> bool:
    global db
    """
    Обновляет метаданные конкретного узла по его ID.
    Используется для изменения parent_id.
    """
    try:
        # ИСПРАВЛЕНО: Замена 'nodes' на 'structure'
        db.collection('structure').document(node_id).update(data)
        
        logging.info(f"Метаданные узла {node_id} обновлены: {data}")
        return True
    except Exception as e:
        logging.error(f"Ошибка при обновлении метаданных узла {node_id}: {e}")
        return False
        
def update_node_order(siblings_data: List[Dict]):
    """Обновляет поле 'order' для списка узлов в одной пакетной операции."""
    global db
    if not db:
        return False

    batch = db.batch()
    try:
        for data in siblings_data:
            node_id = data.get('id')
            new_order = data.get('order')

            if node_id is not None and new_order is not None:
                doc_ref = db.collection('structure').document(node_id)
                # Убеждаемся, что `order` сохраняется как целое число
                batch.update(doc_ref, {'order': int(new_order)}) 

        batch.commit()
        return True
    except Exception as e:
        logging.error(f"Ошибка при массовом обновлении порядка узлов: {e}")
        return False
# ==================== ФУНКЦИИ REALTIME LISTENER ====================
def start_structure_listener(firebase_signals: FirebaseSignals):
    """
    Устанавливает Realtime Listener на коллекцию 'structure'. 
    Использует замыкание для доступа к firebase_signals и call_count.
    """
    global db, listener_running

    if not db: 
        logging.error("Firestore не инициализирован для запуска слушателя.")
        return None
    
    # Переменная для подсчета вызовов, будет доступна через замыкание (nonlocal)
    call_count = 0 
    
    def on_snapshot(query_snapshot, changes, read_time):
        nonlocal call_count
        call_count += 1
            
        if not changes:
            return

        # 1. ПЕРВЫЙ ВЫЗОВ (Initial Load). Принимаем его для заполнения дерева.
        if call_count == 1:
            reason = "ПЕРВОНАЧАЛЬНАЯ ЗАГРУЗКА"
            logging.info(f"Realtime-слушатель: {reason} структуры.")
            firebase_signals.guides_structure_changed.emit()
                
        # 2. ВТОРОЙ ВЫЗОВ (Дубликат Initial Snapshot). Игнорируем.
        elif call_count == 2:
            logging.debug("Realtime-слушатель: Пропуск второго (дублирующего) 'Initial Snapshot'.")
            return

        # 3. ВСЕ ПОСЛЕДУЮЩИЕ ВЫЗОВЫ (Realtime Changes) - принимаем.
        else:
            reason = "ФАКТИЧЕСКОЕ ИЗМЕНЕНИЕ"
            logging.info(f"Обнаружено изменение в структуре гайдов ({reason}). Количество изменений: {len(changes)}. Инициирую обновление через сигнал.")
            firebase_signals.guides_structure_changed.emit()

    try:
        col_ref = db.collection('structure')
        # Запуск слушателя. col_watch - это функция отписки.
        col_watch = col_ref.on_snapshot(on_snapshot)
        listener_running = True
        logging.info("Слушатель структуры Firebase успешно запущен.")
        return col_watch
        
    except Exception as e:
        logging.error(f"Ошибка установки слушателя структуры: {e}")
        listener_running = False
        return None