# views/tree_handler.py
import logging
from typing import TYPE_CHECKING
from PyQt6.QtWidgets import QMenu, QInputDialog, QMessageBox, QTreeWidgetItem
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QIcon, QAction
import qtawesome as qta

from config import DEFAULT_GUIDE_CONTENT
from core.firebase_service import (
    get_structure_metadata, get_all_guides_for_search_new,
    create_new_node, rename_node, delete_node_recursively,
    start_structure_listener
)
from core.signals import FirebaseSignals

if TYPE_CHECKING:
    from views.main_window import MainWindow

class TreeHandlerMixin:
    """Mixin для обработки дерева структуры гайдов."""

    def init_tree(self):
        """Инициализация компонентов, связанных с деревом."""
        self.tree = None  # Будет инициализировано в _create_sidebar
        self.guide_map = {}
        self.search_cache = {}
        """Инициализация сигнального объекта"""
        self.firebase_signals = FirebaseSignals()
        """Переменная для хранения функции отписки"""
        self.unsubscribe_structure_listener = None
        """Подключение сигнала Realtime Listener к слоту обновления"""
        self.firebase_signals.guides_structure_changed.connect(self._handle_structure_update)

    """Новый слот для обработки сигнала"""
    def _handle_structure_update(self):
        """Слот для обработки сигнала об изменении структуры гайдов из Firestore."""
        logging.info("Realtime-сигнал об изменении структуры получен. Запуск обновления дерева.")
        self.repopulate_tree("REALTIME_UPDATE")

    """Новый метод для запуска слушателя"""
    def start_realtime_listeners(self):
        """Запуск слушателя изменений в коллекции 'structure'."""
        if not self.unsubscribe_structure_listener:
            # Вызываем функцию из firebase_service для запуска слушателя
            self.unsubscribe_structure_listener = start_structure_listener(self.firebase_signals)
            if self.unsubscribe_structure_listener:
                logging.info("Слушатель структуры Firebase успешно запущен.")
            else:
                logging.error("Не удалось запустить слушатель структуры Firebase.")

    def populate_tree(self, reason: str = "ЗАПУCК ПРИЛОЖЕНИЯ У ПОЛЬЗОВАТЕЛЯ."):
        """Заполняет дерево гайдов на основе метаданных структуры из Firestore."""
        self.tree.clear()
        self.guide_map.clear()

        nodes = get_structure_metadata()
        if not nodes:
            logging.warning("Не удалось загрузить структуру гайдов.")
            return

        root_items = {}
        for node in sorted(nodes, key=lambda x: x.get('order', 0)):
            item = QTreeWidgetItem([node['name']])
            item.setData(0, Qt.ItemDataRole.UserRole, node['id'])
            item.setData(0, Qt.ItemDataRole.UserRole + 1, node['type'])

            icon = qta.icon("fa5s.file-alt", color="#e0e0e0") if node['type'] == 'guide' else qta.icon("fa5s.folder", color="#ffd700")
            item.setIcon(0, icon)

            if self.is_editable:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)

            parent_id = node.get('parent_id')
            if not parent_id:
                self.tree.addTopLevelItem(item)
                root_items[node['id']] = item
            else:
                parent_item = root_items.get(parent_id)
                if parent_item:
                    parent_item.addChild(item)
                    root_items[node['id']] = item
                else:
                    logging.warning(f"Родитель {parent_id} не найден для узла {node['id']}.")

            self.guide_map[node['id']] = node['name']

        self.tree.expandAll()
        self.search_cache = get_all_guides_for_search_new()
        logging.info(f"Дерево гайдов обновлено: {len(nodes)} узлов.")

    def repopulate_tree(self,reason: str = "ОБЩЕЕ ОБНОВЛЕНИЕ У ПОЛЬЗОВАТЕЛЕЙ."):
        """Перезагружает дерево и обновляет текущий гайд."""
        self.populate_tree(reason )
        if self.current_guide_fn:
            self.load_guide_by_node_id(self.current_guide_fn)

    def on_tree_item_clicked(self, item: QTreeWidgetItem, column: int):
        """Обрабатывает клик по элементу дерева."""
        node_id = item.data(0, Qt.ItemDataRole.UserRole)
        node_type = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if node_type == 'guide':
            self.load_guide_by_node_id(node_id)

    def on_tree_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        """Обрабатывает двойной клик по элементу дерева (переименование для редакторов)."""
        if self.is_editable:
            self.tree.editItem(item, column)

    def search_guides(self, query: str):
        """Ищет гайды по тексту в заголовках и контенте."""
        if not query.strip():
            self.tree.clearSelection()
            return

        query_lower = query.lower()
        found_items = []

        for item in self.tree.findItems("", Qt.MatchFlag.MatchRecursive | Qt.MatchFlag.MatchContains):
            node_id = item.data(0, Qt.ItemDataRole.UserRole)
            if not node_id: continue

            title = self.guide_map.get(node_id, "").lower()
            content = self.search_cache.get(node_id, {}).get('content', "").lower()

            if query_lower in title or query_lower in content:
                found_items.append(item)

        self.tree.clearSelection()
        for item in found_items:
            item.setSelected(True)
            parent = item.parent()
            while parent:
                parent.setExpanded(True)
                parent = parent.parent()

    def highlight_search_results(self):
        """Подсвечивает результаты поиска в webview (если применимо)."""
        # Логика подсветки может быть добавлена позже
        pass

    def show_context_menu(self, position: QPoint):
        """Показывает контекстное меню для дерева."""
        menu = QMenu()

        item = self.tree.itemAt(position)

        # 1. Сценарий: Нажатие на пустое место
        if not item:
            root_id = None 
            
            if self.is_editable: # <--- Добавляем проверку прав только здесь
                add_guide_action = QAction(qta.icon("fa5s.file-alt", color="#e0e0e0"), "Добавить гайд", self)
                add_guide_action.triggered.connect(lambda: self.add_new_guide(root_id))
                menu.addAction(add_guide_action)

                add_folder_action = QAction(qta.icon("fa5s.folder-plus", color="#ffd700"), "Добавить папку", self)
                add_folder_action.triggered.connect(lambda: self.add_new_folder(root_id))
                menu.addAction(add_folder_action)

            # Показываем меню и завершаем выполнение функции
            menu.exec(self.tree.viewport().mapToGlobal(position))
            return # <-- Обязательно выходим, независимо от is_editable

        # Дальнейший код выполняется только если был нажат элемент (item is not None)
        
        # Проверка редактируемости должна быть в начале этого блока
        if not self.is_editable: 
            # Для нередактируемых пользователей на элементе, показываем пустое меню (или с общими действиями, если есть)
            menu.exec(self.tree.viewport().mapToGlobal(position))
            return

        # Если is_editable == True (редактор) и item is not None
        node_id = item.data(0, Qt.ItemDataRole.UserRole)
        node_type = item.data(0, Qt.ItemDataRole.UserRole + 1)

        # 2. Сценарий: Нажатие на папку (редактор)
        if node_type == 'folder':
            add_guide_action = QAction(qta.icon("fa5s.file-alt", color="#e0e0e0"), "Добавить гайд", self)
            add_guide_action.triggered.connect(lambda: self.add_new_guide(node_id))
            menu.addAction(add_guide_action)

            add_folder_action = QAction(qta.icon("fa5s.folder-plus", color="#ffd700"), "Добавить папку", self)
            add_folder_action.triggered.connect(lambda: self.add_new_folder(node_id))
            menu.addAction(add_folder_action)

        # 3. Сценарий: Нажатие на любой редактируемый элемент (папку или гайд)
        if menu.actions():
            menu.addSeparator() # Добавляем разделитель, если уже есть действия

        rename_action = QAction(qta.icon("fa5s.edit", color="#e0e0e0"), "Переименовать", self)
        rename_action.triggered.connect(lambda: self.rename_node_dialog(node_id, item.text(0)))
        menu.addAction(rename_action)

        delete_action = QAction(qta.icon("fa5s.trash-alt", color="#ff6b6b"), "Удалить", self)
        delete_action.triggered.connect(lambda: self.delete_node_dialog(node_id, item.text(0)))
        menu.addAction(delete_action)

        menu.exec(self.tree.viewport().mapToGlobal(position))

    def add_new_guide(self, parent_id: str):
        """Добавляет новый гайд в указанную папку."""
        name, ok = QInputDialog.getText(self, "Новый гайд", "Введите название гайда:")
        if ok and name.strip():
            new_id = create_new_node(name.strip(), parent_id, 'guide', DEFAULT_GUIDE_CONTENT(name.strip()))
            if new_id:
                reason = f"Добавление нового гайда: '{name.strip()}' (ID: {new_id})"
                self.repopulate_tree(reason) # Передаем причину
            else:
                QMessageBox.critical(self, "Ошибка", "Не удалось создать гайд.")

    def add_new_folder(self, parent_id: str):
        """Добавляет новую папку в указанную папку."""
        name, ok = QInputDialog.getText(self, "Новая папка", "Введите название папки:")
        if ok and name.strip():
            new_id = create_new_node(name.strip(), parent_id, 'folder')
            if new_id:
                reason = f"Добавление новой папки: '{name.strip()}' (ID: {new_id})"
                self.repopulate_tree(reason) # Передаем причину
            else:
                QMessageBox.critical(self, "Ошибка", "Не удалось создать папку.")

    def rename_node_dialog(self, node_id: str, old_name: str):
        """Диалог переименования узла."""
        if node_id in ['root_info', 'folder_maps', 'root_settings']:
            QMessageBox.warning(self, "Ошибка", f"Нельзя переименовать базовый узел '{old_name}'.")
            return

        new_name, ok = QInputDialog.getText(self, "Переименовать", "Новое название:", text=old_name)
        if ok and new_name.strip() and new_name != old_name:
            if rename_node(node_id, new_name.strip()):
                QMessageBox.information(self, "Успех", f"Узел '{old_name}' переименован в '{new_name.strip()}'")
                reason = f"Переименование узла: {new_name.strip()} | ID: {node_id})"
                self.repopulate_tree(reason) # Передаем причину
            else:
                QMessageBox.critical(self, "Ошибка", "Не удалось переименовать узел.")

    def delete_node_dialog(self, node_id: str, name: str) -> bool:
        """Диалог подтверждения удаления узла (рекурсивно)."""
        if node_id in ['root_info', 'folder_maps', 'root_settings']:
            QMessageBox.warning(self, "Ошибка", f"Нельзя удалить базовый узел '{name}'.")
            return False

        reply = QMessageBox.question(self, "Удалить узел",
                                     f"Удалить '{name}' и все содержимое рекурсивно?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            if delete_node_recursively(node_id):
                reason = f"Удаление узла: {name.strip()} | ID: {node_id})"
                self.repopulate_tree(reason) # Передаем причину
                QMessageBox.information(self, "Успех", f"Узел '{name}' и содержимое удалены.")
                self.repopulate_tree()
                return True
            else:
                QMessageBox.critical(self, "Ошибка", "Не удалось удалить узел.")
        return False
