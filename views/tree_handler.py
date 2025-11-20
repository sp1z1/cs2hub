# views/tree_handler.py
import logging
from typing import TYPE_CHECKING, Optional, List, Dict 

from PyQt6.QtWidgets import (
    QMenu, QInputDialog, QMessageBox, 
    QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QLabel, QListView 
)
from PyQt6.QtCore import Qt, QPoint, QTimer, QModelIndex
from PyQt6.QtGui import QStandardItem
import qtawesome as qta

from config import DEFAULT_GUIDE_CONTENT
# 🚀 ИСПРАВЛЕНО: Добавлен импорт 'db' для Drag-and-Drop
from core.firebase_service import (
    get_structure_metadata, create_new_node, rename_node,
    delete_node_recursively, start_structure_listener,
    get_all_guides_for_search_new,
    update_structure_after_drag_and_drop
)
from core.firebase_service import firebase_signals, start_structure_listener, stop_structure_listener
from views.custom_tree_view import CustomTreeView

if TYPE_CHECKING:
    from views.main_window import MainWindow


ICON_CHOICES: Dict[str, List[tuple]] = {
    'guide': [
        ("fa5s.users", "#50E3C2"),    # Бирюзовый
        ("fa5s.stream", "#9B59B6"),   # Фиолетовый
        ("fa5s.book-open", "#F5A623"),# Оранжевый
        ("mdi6.strategy", "#54D051"), # Ярко-зеленый
        ("ri.list-settings-line", "#E777A3"), # Розовый
        ("fa5s.file-alt", "#A9B7C6"), # Нейтральный Серый
    ],
    'folder': [
        # Структура, Файлы
        ("fa5s.folder-open", "#F8E71C"),     # Желтый (Классическая папка)
        ("fa5s.map-marked-alt", "#4A90E2"),  # Синий (Карта)
        ("fa5s.sitemap", "#50E3C2"),         # Бирюзовый (Структура)
    ]
}
# Иконки по умолчанию для новых элементов
DEFAULT_GUIDE_ICON = ICON_CHOICES['guide'][0]
DEFAULT_FOLDER_ICON = ICON_CHOICES['folder'][0]

# ==================== КАСТОМНЫЙ ДИАЛОГ ВЫБОРА ИКОНКИ (Визуальное отображение) ====================
class IconSelectionDialog(QDialog):
    """Кастомный диалог с QComboBox для визуального выбора Qtawesome иконки."""
    def __init__(self, node_type: str, current_icon_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Выбор иконки")
        self.setFixedSize(300, 150)
        
        self.choices = ICON_CHOICES.get(node_type, [])
        self.selected_icon_name = None

        main_layout = QVBoxLayout(self)

        # 1. ComboBox для выбора
        self.icon_combo = QComboBox(self)
        self.icon_combo.setView(QListView()) # Улучшает отображение элементов
        self.icon_combo.setIconSize(self.icon_combo.iconSize() * 1.5) # Немного увеличим иконки

        default_index = 0
        
        for i, (name, color) in enumerate(self.choices):
            # name теперь гарантированно является рабочим именем иконки
            icon = qta.icon(name, color=color) 
            # Используем QIcon в addItem(), чтобы QComboBox отобразил иконку
            self.icon_combo.addItem(icon, name) 
            
            if name == current_icon_name:
                default_index = i
        
        self.icon_combo.setCurrentIndex(default_index)

        main_layout.addWidget(QLabel("Выберите иконку:"))
        main_layout.addWidget(self.icon_combo)

        # 2. Кнопки
        btn_layout = QHBoxLayout()
        btn_ok = QPushButton("ОК")
        btn_cancel = QPushButton("Отмена")
        
        btn_ok.clicked.connect(self._accept_selection)
        btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_ok)
        main_layout.addLayout(btn_layout)

    def _accept_selection(self):
        # Получаем выбранное имя иконки, которое мы сохранили как текст элемента
        self.selected_icon_name = self.icon_combo.currentText()
        self.accept()

    @staticmethod
    def getIconChoice(node_type: str, current_icon_name: str, parent=None) -> Optional[str]:
        """Статический метод для запуска диалога и получения результата."""
        dialog = IconSelectionDialog(node_type, current_icon_name, parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.selected_icon_name
        return None

# ==================== MIXIN ОБРАБОТЧИКА ДЕРЕВА ====================
class TreeHandlerMixin:
    """Mixin для работы с деревом на QTreeView + QStandardItemModel"""
    
    # ⚠️ ПРЕДПОЛАГАЕТСЯ: В РЕАЛЬНОМ ПРИЛОЖЕНИИ ЭТА ПЕРЕМЕННАЯ УСТАНАВЛИВАЕТСЯ ПРИ АУТЕНТИФИКАЦИИ
    def __init__(self):
        super().__init__()
        # 🛑 ЗАГЛУШКА: Установите True для администратора, False для обычного пользователя.
        self.is_editable = True 

    def init_tree(self):
        self.tree = CustomTreeView(handler=self)
        self.guide_map = {}
        self.search_cache = {}
        self.is_searching = False # Флаг для режима поиска

        self.firebase_signals = firebase_signals
        self.unsubscribe_structure_listener = None
        self.firebase_signals.guides_structure_changed.connect(self._handle_structure_update)

        # 1. Таймер для Realtime Listener (Debounce)
        self.repopulate_timer = QTimer(self.tree)
        self.repopulate_timer.setSingleShot(True)
        self.repopulate_timer.setInterval(300)
        self.repopulate_timer.timeout.connect(self.populate_tree)

        # 2. Таймер для поля поиска (Debounce)
        self.search_timer = QTimer(self.tree) 
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(300)
        self.search_timer.timeout.connect(self.perform_search)
        
    def perform_search(self):
        # ⚠️ ПРЕДПОЛАГАЕТСЯ: self.search_input существует в основном классе
        query = self.search_input.text().strip()
        
        if not query:
            if self.is_searching:
                self.is_searching = False
                self.populate_tree() 
            return
            
        self.is_searching = True
        logging.info(f"Выполняется поиск по запросу: {query}")
        
        if not self.search_cache:
            self.search_cache = get_all_guides_for_search_new()
            logging.info(f"Кэш поиска загружен: {len(self.search_cache)} гайдов.")

        results = {}
        for node_id, data in self.search_cache.items():
            if query.lower() in data['title'].lower() or query.lower() in data['content'].lower():
                results[node_id] = data

        self.populate_tree_search(results)

    def populate_tree_search(self, results: dict):
        """Отображает результаты поиска в виде плоского списка."""
        self.tree.model.clear()
        
        if not results:
            item = QStandardItem("Ничего не найдено")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.tree.model.appendRow(item)
            return

        for node_id, data in results.items():
            item = QStandardItem(data['title'])
            item.setData(node_id, Qt.ItemDataRole.UserRole)
            item.setData('guide', Qt.ItemDataRole.UserRole + 1)
            # 💡 Использование иконки по умолчанию из новых констант
            icon = qta.icon(DEFAULT_GUIDE_ICON[0], color=DEFAULT_GUIDE_ICON[1])
            item.setIcon(icon)
            # Отключаем D&D и редактирование в поиске
            item.setFlags(item.flags() & ~(Qt.ItemFlag.ItemIsDropEnabled | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsEditable)) 
            self.tree.model.appendRow(item)


    def _handle_structure_update(self):
        if not self.is_searching: 
            self.repopulate_timer.start()

    def start_realtime_listeners(self):
        self.unsubscribe_structure_listener = start_structure_listener()

    def stop_realtime_listeners(self):
        try:
            firebase_signals.guides_structure_changed.disconnect(self._handle_structure_update)
        except:
            pass
        stop_structure_listener()
        self.unsubscribe_structure_listener = None

    # ==================== КЛИКИ ПО ДЕРЕВУ ====================
    def on_tree_item_clicked(self, index: QModelIndex):
        if not index.isValid():
            return
        item = self.tree.model.itemFromIndex(index)
        if not item:
            return
        node_id = item.data(Qt.ItemDataRole.UserRole)
        node_type = item.data(Qt.ItemDataRole.UserRole + 1)
        if node_type == "guide" and node_id:
            # ⚠️ ПРЕДПОЛАГАЕТСЯ: self.load_guide_by_node_id существует
            self.load_guide_by_node_id(node_id) 
            

    def on_tree_item_double_clicked(self, index: QModelIndex):
        if not index.isValid():
            return
        item = self.tree.model.itemFromIndex(index)
        if not item:
            return
        node_type = item.data(Qt.ItemDataRole.UserRole + 1)
        if node_type == "folder":
            self.tree.setExpanded(index, not self.tree.isExpanded(index))
        elif node_type == "guide":
            node_id = item.data(Qt.ItemDataRole.UserRole)
            if node_id:
                # ⚠️ ПРЕДПОЛАГАЕТСЯ: self.load_guide_by_node_id существует
                self.load_guide_by_node_id(node_id)
                


    # ==================== КОНТЕКСТНОЕ МЕНЮ ====================
    def show_context_menu(self, position: QPoint):
        if self.is_searching:
            return

        index = self.tree.indexAt(position)
        item = self.tree.model.itemFromIndex(index) if index.isValid() else None
        
        node_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        node_type = item.data(Qt.ItemDataRole.UserRole + 1) if item else None
        
        # Определяем родителя для добавления
        target_id_for_add = None
        if node_type == "folder":
            target_id_for_add = node_id
        elif node_type == "guide":
            parent_index = index.parent()
            parent_item = self.tree.model.itemFromIndex(parent_index) if parent_index.isValid() else None
            target_id_for_add = parent_item.data(Qt.ItemDataRole.UserRole) if parent_item else None
        elif not item:
             target_id_for_add = None
        
        menu = QMenu(self.tree)

        # 🛑 Контроль доступа: Добавление
        if self.is_editable and (target_id_for_add is not None or not index.isValid()):
            # 💡 Использование иконки по умолчанию из новых констант
            add_guide_action = menu.addAction(qta.icon(DEFAULT_GUIDE_ICON[0], color=DEFAULT_GUIDE_ICON[1]), "Добавить гайд")
            add_guide_action.triggered.connect(lambda: self.add_new_guide(target_id_for_add))

            # 💡 Использование иконки по умолчанию из новых констант
            add_folder_action = menu.addAction(qta.icon(DEFAULT_FOLDER_ICON[0], color=DEFAULT_FOLDER_ICON[1]), "Добавить папку")
            add_folder_action.triggered.connect(lambda: self.add_new_folder(target_id_for_add))
            
            if node_id not in ['root_info', 'folder_maps', 'root_settings']:
                menu.addSeparator()

        # 🛑 Контроль доступа: Переименование/Удаление
        if item and self.is_editable and node_id and node_id not in ['root_info', 'folder_maps', 'root_settings']:
            # 💡 Изменено: Переименование теперь включает выбор иконки
            rename_action = menu.addAction(qta.icon("fa5s.edit", color="#e0e0e0"), "Переименовать и сменить иконку")
            rename_action.triggered.connect(lambda: self.rename_node_and_icon_dialog(node_id, item.text(), node_type))

            delete_action = menu.addAction(qta.icon("fa5s.trash-alt", color="#ff6b6b"), "Удалить")
            delete_action.triggered.connect(lambda: self.delete_node_dialog(node_id, item.text()))

        if menu.actions():
            menu.exec(self.tree.viewport().mapToGlobal(position))

    # 🚀 ИСПРАВЛЕНО: Теперь вызывает IconSelectionDialog и передает icon_name
    def add_new_guide(self, parent_id: Optional[str]):
        # 🛑 Проверка прав
        if not self.is_editable:
            QMessageBox.warning(self, "Ошибка доступа", "Недостаточно прав для создания гайда.")
            return

        name, ok = QInputDialog.getText(self, "Новый гайд", "Введите название гайда:")
        if ok and name.strip():
            # 💡 Вызываем кастомный диалог с визуальным выбором
            icon_name = IconSelectionDialog.getIconChoice('guide', DEFAULT_GUIDE_ICON[0], parent=self.tree)
            if icon_name:
                create_new_node(name.strip(), parent_id, 'guide', DEFAULT_GUIDE_CONTENT(name.strip()), icon_name=icon_name)

    # 🚀 ИСПРАВЛЕНО: Теперь вызывает IconSelectionDialog и передает icon_name
    def add_new_folder(self, parent_id: Optional[str]):
        # 🛑 Проверка прав
        if not self.is_editable:
            QMessageBox.warning(self, "Ошибка доступа", "Недостаточно прав для создания папки.")
            return

        name, ok = QInputDialog.getText(self, "Новая папка", "Введите название папки:")
        if ok and name.strip():
            # 💡 Вызываем кастомный диалог с визуальным выбором
            icon_name = IconSelectionDialog.getIconChoice('folder', DEFAULT_FOLDER_ICON[0], parent=self.tree)
            if icon_name:
                 create_new_node(name.strip(), parent_id, 'folder', icon_name=icon_name)

    # 💡 НОВОЕ: Диалог переименования с возможностью смены иконки
    def rename_node_and_icon_dialog(self, node_id: str, old_name: str, node_type: str):
        # 🛑 Проверка прав
        if not self.is_editable:
            QMessageBox.warning(self, "Ошибка доступа", "Недостаточно прав для переименования.")
            return

        # 1. Запрашиваем новое имя
        new_name, ok_name = QInputDialog.getText(self, "Переименовать", "Новое название:", text=old_name)
        if not ok_name or not new_name.strip():
            return
        
        # 2. Запрашиваем новую иконку
        
        # Ищем текущее имя иконки для установки по умолчанию в диалоге
        current_icon_name = None
        for item_id in self.guide_map:
            if item_id == node_id:
                # В текущем коде у нас нет простого способа получить icon_name из item.
                # Поэтому пока используем дефолтную иконку как заглушку.
                # В идеале, нужно брать icon_name из данных узла, но для простоты:
                current_icon_name = DEFAULT_GUIDE_ICON[0] if node_type == 'guide' else DEFAULT_FOLDER_ICON[0]
                break

        # 💡 Вызываем кастомный диалог с визуальным выбором
        new_icon_name = IconSelectionDialog.getIconChoice(node_type, current_icon_name, parent=self.tree)

        if new_icon_name or new_name.strip() != old_name:
            # 🚀 ИСПРАВЛЕНО: Вызываем rename_node с новым именем и новой иконкой (если выбрана)
            if rename_node(node_id, new_name.strip(), icon_name=new_icon_name):
                 QMessageBox.information(self, "Успех", f"Узел переименован и/или иконка обновлена в «{new_name.strip()}»")
            else:
                 QMessageBox.critical(self, "Ошибка", "Не удалось переименовать или сменить иконку в Firebase.")

    def delete_node_dialog(self, node_id: str, name: str):
        # 🛑 Проверка прав
        if not self.is_editable:
            QMessageBox.warning(self, "Ошибка доступа", "Недостаточно прав для удаления.")
            return

        if node_id in ['root_info', 'folder_maps', 'root_settings']:
            QMessageBox.warning(self, "Ошибка", "Нельзя удалить системный узел.")
            return
        reply = QMessageBox.question(
            self, "Удалить узел",
            f"Удалить «{name}» и всё содержимое рекурсивно?\nЭто действие нельзя отменить.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            if delete_node_recursively(node_id):
                QMessageBox.information(self, "Успех", f"Узел «{name}» удалён")
                
    # ==================== ПОСТРОЕНИЕ ДЕРЕВА ====================
    def populate_tree(self):
        """Строит полное дерево из метаданных Firestore."""
        logging.info("Перестройка дерева (QTreeView + QStandardItemModel)")
        self.is_searching = False 
        
        # 1. Сохраняем состояние
        expanded_ids = set()
        selected_id = None
        current_index = self.tree.currentIndex()
        if current_index.isValid():
            item = self.tree.model.itemFromIndex(current_index)
            if item:
                selected_id = item.data(Qt.ItemDataRole.UserRole)

        def collect_expanded(item: Optional[QStandardItem]):
            if not item: return
            node_id = item.data(Qt.ItemDataRole.UserRole)
            if node_id and self.tree.isExpanded(item.index()):
                expanded_ids.add(node_id)
            for i in range(item.rowCount()):
                collect_expanded(item.child(i))

        root = self.tree.model.invisibleRootItem()
        for i in range(root.rowCount()):
            collect_expanded(root.child(i))

        # 2. Очищаем и загружаем
        self.tree.model.clear()
        self.guide_map.clear()

        nodes = get_structure_metadata()
        if not nodes:
            logging.warning("Не удалось загрузить структуру")
            return

        nodes_by_parent = {}
        for node in nodes:
            parent_key = node.get('parent_id') 
            nodes_by_parent.setdefault(parent_key, []).append(node)

        def create_item(node: dict) -> QStandardItem:
            item = QStandardItem(node['name'])
            item.setData(node['id'], Qt.ItemDataRole.UserRole)
            item.setData(node['type'], Qt.ItemDataRole.UserRole + 1)
            
            node_type = node['type']
            icon_name = node.get('icon_name')
            icon_color = None
            default_icon, default_color = DEFAULT_GUIDE_ICON if node_type == 'guide' else DEFAULT_FOLDER_ICON

            if not icon_name:
                # Если иконка не задана (старые данные), используем дефолт
                icon_name, icon_color = default_icon, default_color
            else:
                # Пытаемся найти сохраненный цвет в ICON_CHOICES
                found_color = False
                # Объединяем все возможные choices для поиска цвета
                all_choices = ICON_CHOICES.get('guide', []) + ICON_CHOICES.get('folder', [])
                for name, color in all_choices:
                    if name == icon_name:
                        icon_color = color
                        found_color = True
                        break
                
                # Если цвет не найден (например, системная иконка), 
                # используем цвет по умолчанию
                if not found_color:
                    icon_color = default_color
            
            # Если цвет все еще None (крайний случай), берем дефолтный
            if icon_color is None:
                icon_color = '#e0e0e0' 
            
            # 🔥 Защита от невалидных иконок, хранящихся в Firebase
            try:
                # Создаем иконку
                icon = qta.icon(icon_name, color=icon_color)
            except Exception as e:
                logging.warning(f"Ошибка при загрузке иконки '{icon_name}' из БД. Используется дефолтная: {e}")
                icon = qta.icon(default_icon, color=default_color)
            
            item.setIcon(icon)
            
            flags = item.flags() | Qt.ItemFlag.ItemIsDropEnabled 
            
            # 🛑 Контроль доступа
            if self.is_editable:
                flags |= Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsDragEnabled
            else:
                # В режиме чтения запрещаем D&D и редактирование
                flags &= ~(Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled)
            
            item.setFlags(flags)
            return item

        def build_tree(parent_item: QStandardItem, parent_id: Optional[str]):
            children = sorted(nodes_by_parent.get(parent_id, []), key=lambda x: x.get('order', 0))
            for node in children:
                item = create_item(node)
                parent_item.appendRow(item)
                self.guide_map[node['id']] = node['name']
                build_tree(item, node['id'])

        # 3. Строим дерево, начиная с корневых элементов (parent_id=None)
        root_item = self.tree.model.invisibleRootItem()
        build_tree(root_item, None)

        # 4. Восстанавливаем состояние
        def restore_expanded(item: QStandardItem):
            if not item: return
            node_id = item.data(Qt.ItemDataRole.UserRole)
            if node_id and node_id in expanded_ids:
                self.tree.expand(item.index())
            for i in range(item.rowCount()):
                restore_expanded(item.child(i))

        for i in range(root_item.rowCount()):
            restore_expanded(root_item.child(i))

        if selected_id:
            self.select_node_by_id(selected_id)

    def select_node_by_id(self, node_id: str):
        def find_item(item: QStandardItem) -> Optional[QStandardItem]:
            if not item: return None
            if item.data(Qt.ItemDataRole.UserRole) == node_id:
                return item
            for i in range(item.rowCount()):
                found = find_item(item.child(i))
                if found:
                    return found
            return None

        root = self.tree.model.invisibleRootItem()
        for i in range(root.rowCount()):
            found = find_item(root.child(i))
            if found:
                index = found.index()
                self.tree.setCurrentIndex(index)
                self.tree.scrollTo(index)
                return

    def handle_tree_structure_change_after_drop(self):
        """Обрабатывает изменения parent_id и order после Drag-and-Drop."""
        # 🛑 Контроль доступа
        if not self.is_editable:
            return

        updates = []

        # --- ВНУТРЕННЯЯ ФУНКЦИЯ ДЛЯ РЕКУРСИВНОГО СБОРА ДАННЫХ ---
        def process_item(item: QStandardItem, parent_id: Optional[str]):
            if not item: return
            node_id = item.data(Qt.ItemDataRole.UserRole)
            if not node_id: return
            
            # Сбор данных для обновления
            # Order = row * 10 для запаса между элементами
            updates.append({
                'id': node_id,
                'parent_id': parent_id,
                'order': item.row() * 10
            })

            # Рекурсия
            next_parent_id = node_id
            for row in range(item.rowCount()):
                process_item(item.child(row), next_parent_id)
        # -----------------------------------------------------

        # 1. Запуск сбора данных от корня
        root = self.tree.model.invisibleRootItem()
        for i in range(root.rowCount()):
            process_item(root.child(i), None)

        # 2. Передача данных в сервис Firebase для пакетной записи
        if updates:
            if update_structure_after_drag_and_drop(updates):
                logging.info("Структура успешно сохранена после drag-and-drop")
                # Обновляем дерево из облака, чтобы восстановить его состояние
                self.populate_tree() 
            else:
                # Если произошла ошибка в Firebase, выводим сообщение и восстанавливаем старую структуру
                QMessageBox.critical(self, "Ошибка", "Не удалось сохранить порядок элементов. Проверьте подключение к Firebase.")
                self.populate_tree()