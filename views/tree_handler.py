# views/tree_handler.py
import logging
from typing import TYPE_CHECKING
from PyQt6.QtWidgets import QMenu, QInputDialog, QMessageBox, QTreeWidgetItem
from PyQt6.QtCore import Qt, QPoint, QTimer # QTimer импортирован, но не используется в оптимизированном D&D
from PyQt6.QtGui import QIcon, QAction
import qtawesome as qta

from config import DEFAULT_GUIDE_CONTENT
from core.firebase_service import (
    get_structure_metadata, get_all_guides_for_search_new,
    create_new_node, rename_node, delete_node_recursively,
    start_structure_listener, listener_running, update_node_metadata, update_node_order
)
from core.signals import FirebaseSignals
from views.custom_widgets import CustomTreeWidget

if TYPE_CHECKING:
    from views.main_window import MainWindow

class TreeHandlerMixin:
    """Mixin для обработки дерева структуры гайдов."""

    def init_tree(self):
        """Инициализация компонентов, связанных с деревом."""
        self.tree = CustomTreeWidget(handler=self)
        # self.is_handling_local_dnd = False <-- УДАЛЕНО: Больше не нужен
        self.guide_map = {}
        self.search_cache = {}
        self.tree.setDragEnabled(True)
        self.tree.setAcceptDrops(True)
        self.tree.setDropIndicatorShown(True)
        self.tree.setDragDropMode(self.tree.DragDropMode.InternalMove)
        self.tree.setSelectionMode(self.tree.SelectionMode.SingleSelection)
        """Инициализация сигнального объекта"""
        self.firebase_signals = FirebaseSignals()
        """Переменная для хранения функции отписки"""
        self.unsubscribe_structure_listener = None
        """ПРЕДОТВРАЩЕНИЕ ПОВТОРНОГО ЗАПУСКА"""
        self._listener_started = False
        """Подключение сигнала Realtime Listener к слоту обновления"""
        self.firebase_signals.guides_structure_changed.connect(self._handle_structure_update)
        # --- ОПТИМИЗАЦИЯ: Таймер для Debouncing ---
        self.repopulate_timer = QTimer(self.tree)
        self.repopulate_timer.setSingleShot(True)
        # Устанавливаем задержку, например, 200 мс. Это время "тишины" между обновлениями.
        self.repopulate_timer.setInterval(200) 
        self.repopulate_timer.timeout.connect(lambda: self.repopulate_tree("DEBOUNCED_UPDATE"))
        # --- КОНЕЦ: Таймер для Debouncing ---

    """Новый слот для обработки сигнала"""
    def _handle_structure_update(self):
        """Слот для обработки сигнала об изменении структуры гайдов из Firestore."""
        # Listener всегда вызывает repopulate_tree, даже после D&D
        self.repopulate_tree("REALTIME_UPDATE")
        self.repopulate_timer.start()

    """Новый метод для запуска слушателя"""
    def start_realtime_listeners(self):
        """Запуск слушателя изменений в коллекции 'structure'."""
        if not self.unsubscribe_structure_listener:
            # Вызываем функцию из firebase_service для запуска слушателя
            self.unsubscribe_structure_listener = start_structure_listener(self.firebase_signals)

    """Остановка слушателя Firebase при закрытии приложения."""
    def stop_realtime_listeners(self):
        global listener_running
        if self.unsubscribe_structure_listener:
            self.unsubscribe_structure_listener()
            self.unsubscribe_structure_listener = None
            logging.info("Слушатель структуры Firebase остановлен.")
            listener_running = False
            
    """Заполняет дерево гайдов на основе метаданных структуры из Firestore."""
    def populate_tree(self, reason: str = "ЗАПУCК ПРИЛОЖЕНИЯ У ПОЛЬЗОВАТЕЛЯ."):
            """
            Заполняет дерево гайдов, используя рекурсивный подход, 
            сохраняя и восстанавливая состояние развертывания и выбора.
            """
            
            # --- ОПТИМИЗАЦИЯ: Сохранение состояния ---
            expanded_ids = {item.data(0, Qt.ItemDataRole.UserRole) 
                            for item in self.tree.findItems("", Qt.MatchFlag.MatchRecursive) 
                            if item.isExpanded() and item.data(0, Qt.ItemDataRole.UserRole)}
            selected_id = self.tree.currentItem().data(0, Qt.ItemDataRole.UserRole) if self.tree.currentItem() else None
            # --- КОНЕЦ: Сохранение состояния ---
            
            self.tree.clear()
            self.guide_map.clear()

            nodes = get_structure_metadata()
            if not nodes:
                logging.warning("Не удалось загрузить структуру гайдов.")
                return

            # 1. Создаем список всех действительных ID узлов для проверки
            valid_node_ids = {node['id'] for node in nodes}
            
            # 2. Сгруппировать узлы по parent_id, отфильтровывая циклические/несуществующие ссылки
            nodes_by_parent = {}
            
            for node in nodes:
                node_id = node['id']
                parent_id = node.get('parent_id')
                
                # Проверка 1: Циклическая зависимость (узел родитель самому себе)
                if parent_id == node_id:
                    logging.error(f"Обнаружен циклический узел (родитель = сам себе): {node_id}. Добавляется как корневой.")
                    parent_id = None
                
                # Проверка 2: Родитель не существует в текущем наборе узлов
                elif parent_id is not None and parent_id not in valid_node_ids:
                    logging.warning(f"Родитель {parent_id} не найден для узла {node_id}. Добавляется как корневой.")
                    parent_id = None

                if parent_id not in nodes_by_parent:
                    nodes_by_parent[parent_id] = []
                nodes_by_parent[parent_id].append(node)
                
            # 3. Рекурсивная функция для построения элементов
            def build_tree_items(parent_id: str | None, parent_widget=None):
                children = nodes_by_parent.get(parent_id) or []
                
                # ИЗМЕНЕНИЕ: Сортировка только по полю 'order'
                sorted_children = sorted(children, key=lambda node: node.get('order', 0))

                for node in sorted_children:
                    item = QTreeWidgetItem([node['name']])
                    item.setData(0, Qt.ItemDataRole.UserRole, node['id'])
                    item.setData(0, Qt.ItemDataRole.UserRole + 1, node['type'])
                    
                    self.guide_map[node['id']] = node['name']
                    
                    icon = qta.icon("fa5s.file-alt", color="#e0e0e0") if node['type'] == 'guide' else qta.icon("fa5s.folder", color="#ffd700")
                    item.setIcon(0, icon)
                    
                    if self.is_editable:
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)

                    if parent_widget is None:
                        self.tree.addTopLevelItem(item)
                    else:
                        parent_widget.addChild(item)
                    
                    # --- ОПТИМИЗАЦИЯ: Восстановление состояния (Expand) ---
                    if node['id'] in expanded_ids:
                        item.setExpanded(True)
                    # --- КОНЕЦ: Восстановление состояния ---
                    
                    build_tree_items(node['id'], item)

            # 4. Запуск построения дерева с корневого уровня (None)
            build_tree_items(None)

            # self.tree.expandAll() <-- УДАЛЕНО: Расширяем только сохраненные узлы
            
            # --- ОПТИМИЗАЦИЯ: Восстановление выбора ---
            if selected_id:
                # Ищем элемент по ID
                items = self.tree.findItems(selected_id, Qt.MatchFlag.MatchRecursive, column=0)
                if items:
                    self.tree.setCurrentItem(items[0])
            # --- КОНЕЦ: Восстановление выбора ---

            self.search_cache = get_all_guides_for_search_new()
            
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
                # Теперь полагаемся на Listener, который вызовет repopulate_tree
                logging.info(f"Запрос на добавление гайда '{name.strip()}' отправлен в Firestore.")
            else:
                QMessageBox.critical(self, "Ошибка", "Не удалось создать гайд.")

    def add_new_folder(self, parent_id: str):
        """Добавляет новую папку в указанную папку."""
        name, ok = QInputDialog.getText(self, "Новая папка", "Введите название папки:")
        if ok and name.strip():
            new_id = create_new_node(name.strip(), parent_id, 'folder')
            if new_id:
                # Теперь полагаемся на Listener, который вызовет repopulate_tree
                logging.info(f"Запрос на добавление папки '{name.strip()}' отправлен в Firestore.")
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
                # Теперь полагаемся на Listener, который вызовет repopulate_tree
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
                # Теперь полагаемся на Listener, который вызовет repopulate_tree
                QMessageBox.information(self, "Успех", f"Узел '{name}' и содержимое удалены.")
                return True
            else:
                QMessageBox.critical(self, "Ошибка", "Не удалось удалить узел.")
        return False
        
    def handle_tree_structure_change(self, moved_item: QTreeWidgetItem):
        """
        Обновляет метаданные Firestore после успешной операции Drag and Drop.
        
        Эта функция отправляет два обновления: 
        1. Изменение родителя (parent_id) для перемещенного узла.
        2. Изменение порядка (order) для всех братьев и сестер.
        
        Оба обновления вызовут Realtime Listener, который автоматически
        перезагрузит дерево у всех пользователей (включая инициатора D&D).
        """
        # Флаг self.is_handling_local_dnd и сброс флага удалены.
        moved_id = moved_item.data(0, Qt.ItemDataRole.UserRole)

        # 1. Определение нового родителя (new_parent_id)
        new_parent_widget = moved_item.parent()
        new_parent_id = None
        
        if new_parent_widget:
            # Получаем ID родителя, если он есть
            new_parent_id = new_parent_widget.data(0, Qt.ItemDataRole.UserRole)
            
        # 2. Обновление родителя в базе данных
        if update_node_metadata(moved_id, {'parent_id': new_parent_id}):
            logging.info(f"Перемещен узел {moved_id}. Новый родитель: {new_parent_id}")
        else:
            logging.error(f"Не удалось обновить parent_id для узла {moved_id}.")

        # 3. Обновление порядка (order) для всех братьев и сестер (по индексу)
        
        # Получаем виджет, содержащий перемещенные элементы
        parent_widget_for_order = moved_item.parent() if moved_item.parent() else self.tree
        siblings_data = []

        is_root = parent_widget_for_order == self.tree
        
        # Определяем функции для подсчета и получения дочерних элементов
        count_func = self.tree.topLevelItemCount if is_root else parent_widget_for_order.childCount
        item_func = self.tree.topLevelItem if is_root else parent_widget_for_order.child

        # Итерируем по всем детям в их текущем ВИЗУАЛЬНОМ порядке
        for i in range(count_func()):
            child_item = item_func(i)
            
            if not child_item: continue

            node_id = child_item.data(0, Qt.ItemDataRole.UserRole)
            # Шаг 10 обеспечивает возможность добавления промежуточных элементов.
            new_order_value = i * 10 
            
            siblings_data.append({
                'id': node_id,
                'order': new_order_value, 
            })
            
        # 4. Сохраняем новый порядок в базу данных
        if update_node_order(siblings_data):
            logging.info(f"Обновлен порядок для {len(siblings_data)} узлов (братьев/сестер {new_parent_id}).")
        else:
            logging.error("Не удалось обновить порядок узлов в Firebase.")
            