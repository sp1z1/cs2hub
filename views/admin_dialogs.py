# views/admin_dialogs.py
import logging
from typing import TYPE_CHECKING, Dict

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QComboBox, QMessageBox, QInputDialog, QLabel, QHeaderView, 
    QWidget, QLineEdit, QProgressBar
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer
import qtawesome as qta

from views.workers import DataLoaderThread, ActionWorkerThread
from core.firebase_service import (
    get_all_users_firestore, set_user_role_firestore, 
    get_structure_metadata, rename_node, delete_node_recursively
)

if TYPE_CHECKING:
    from views.main_window import MainWindow

# --- ОБЩИЙ СТИЛЬ (Оставляем без изменений) ---
DIALOG_STYLE = """
    QDialog { background-color: #1a1a1a; color: #e0e0e0; }
    QLabel { color: #e0e0e0; font-size: 14px; margin-bottom: 5px; }
    QLineEdit { background-color: #232323; border: 1px solid #4a4a4a; padding: 6px; color: #e0e0e0; border-radius: 4px; }
    QTableWidget {
        background-color: #232323; border: 1px solid #333333; color: #e0e0e0;
        gridline-color: #3a3a3a; selection-background-color: #00ff85; selection-color: black; border-radius: 4px;
    }
    QHeaderView::section { background-color: #333333; color: #e0e0e0; padding: 6px; border: 1px solid #3a3a3a; }
    QTableCornerButton::section { background-color: #333333; border: 1px solid #3a3a3a; }
    QPushButton { background-color: #333333; border: 1px solid #4a4a4a; padding: 6px 12px; border-radius: 4px; color: #e0e0e0; }
    QPushButton:hover { background-color: #4a4a4a; }
    QPushButton#save_btn { background-color: #008f4c; border: 1px solid #00ff85; color: black; font-weight: bold; }
    QPushButton#save_btn:hover { background-color: #00ff85; }
    QComboBox { background-color: #2a2a2a; border: 1px solid #4a4a4a; padding: 4px; border-radius: 4px; color: #e0e0e0; }
"""

class BaseAdminDialog(QDialog):
    """Базовый класс для диалогов с общими методами статуса"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #00ff85; font-weight: bold;")
        self.loading_worker = None
        self.action_worker = None

    def show_loading(self, text="Загрузка данных..."):
        self.status_label.setText(text)
        self.setEnabled(False) # Блокируем интерфейс во время загрузки

    def hide_loading(self):
        self.status_label.setText("")
        self.setEnabled(True)

    def show_error(self, message):
        self.hide_loading()
        QMessageBox.critical(self, "Ошибка", message)


# --- УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ ---

class UserManagementDialog(BaseAdminDialog):
    def __init__(self, parent: 'MainWindow'):
        super().__init__(parent)
        self.setWindowTitle("Управление пользователями")
        self.setMinimumSize(700, 500)
        self.users_data = {} # Полный список
        self.filtered_data = {} # Отфильтрованный список

        self.setup_ui()
        self.setStyleSheet(DIALOG_STYLE)
        self.load_users()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Верхняя панель: Заголовок + Поиск
        top_panel = QHBoxLayout()
        top_panel.addWidget(QLabel("Поиск по логину:"))
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Введите логин...")
        self.search_input.textChanged.connect(self.filter_users)
        top_panel.addWidget(self.search_input)
        layout.addLayout(top_panel)

        # Таблица
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Логин", "Текущая роль", "Новая роль"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table)

        # Статус и кнопки
        layout.addWidget(self.status_label)
        
        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton(qta.icon("fa5s.save", color="black"), "Сохранить изменения")
        self.btn_save.setObjectName("save_btn")
        self.btn_save.clicked.connect(self.save_changes)
        
        self.btn_refresh = QPushButton(qta.icon("fa5s.sync", color="#e0e0e0"), "Обновить")
        self.btn_refresh.clicked.connect(self.load_users)

        btn_layout.addWidget(self.btn_save)
        btn_layout.addWidget(self.btn_refresh)
        layout.addLayout(btn_layout)

    def load_users(self):
        self.show_loading("Загрузка списка пользователей...")
        self.table.setRowCount(0)
        
        self.loading_worker = DataLoaderThread(get_all_users_firestore)
        self.loading_worker.data_loaded.connect(self.on_users_loaded)
        self.loading_worker.error_occurred.connect(self.show_error)
        self.loading_worker.start()

    def on_users_loaded(self, data):
        self.hide_loading()
        if not isinstance(data, dict):
            self.show_error("Получены некорректные данные.")
            return
            
        self.users_data = data
        self.filter_users() # Отображаем данные (с учетом фильтра, если он есть)

    def filter_users(self):
        """Фильтрация локального списка без запросов к БД"""
        query = self.search_input.text().lower()
        self.filtered_data = {
            k: v for k, v in self.users_data.items() 
            if query in k.lower()
        }
        self.populate_table()

    def populate_table(self):
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.filtered_data))
        roles = ["reader", "editor", "admin"]

        for row, (login, data) in enumerate(self.filtered_data.items()):
            role = data.get('role', 'reader')
            
            # Логин
            login_item = QTableWidgetItem(login)
            login_item.setFlags(login_item.flags() ^ Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, login_item)
            
            # Текущая роль
            role_item = QTableWidgetItem(role.capitalize())
            role_item.setFlags(role_item.flags() ^ Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 1, role_item)
            
            # Выбор
            role_combo = QComboBox()
            role_combo.addItems([r.capitalize() for r in roles])
            role_combo.setCurrentText(role.capitalize())
            # Сохраняем оригинальный логин в свойство виджета, чтобы потом найти при сохранении
            role_combo.setProperty("user_login", login) 
            self.table.setCellWidget(row, 2, role_combo)

    def save_changes(self):
        # Собираем изменения
        changes = []
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, 2)
            if combo:
                login = combo.property("user_login")
                new_role = combo.currentText().lower()
                old_role = self.users_data.get(login, {}).get('role', 'reader')
                
                if new_role != old_role:
                    changes.append((login, new_role))
        
        if not changes:
            QMessageBox.information(self, "Инфо", "Нет изменений для сохранения.")
            return

        # Запускаем последовательное сохранение (или пакетное, если API позволяет, но пока по одному)
        self.process_save_queue(changes)

    def process_save_queue(self, changes_queue):
        """Рекурсивная обработка очереди изменений"""
        if not changes_queue:
            self.hide_loading()
            QMessageBox.information(self, "Успех", "Все роли обновлены.")
            self.load_users()
            return

        login, new_role = changes_queue[0]
        remaining = changes_queue[1:]
        
        self.show_loading(f"Сохранение роли для {login}...")
        
        self.action_worker = ActionWorkerThread(
            set_user_role_firestore, 
            "OK", "Fail",
            login, new_role
        )
        self.action_worker.finished.connect(lambda success, msg: self.on_save_step(success, msg, remaining))
        self.action_worker.start()

    def on_save_step(self, success, msg, remaining_queue):
        if not success:
            self.hide_loading()
            QMessageBox.warning(self, "Ошибка", f"Сбой при сохранении. {msg}")
            # Можно прервать или продолжить. Здесь прерываем.
            return
        self.process_save_queue(remaining_queue)


# --- УПРАВЛЕНИЕ ГАЙДАМИ ---

class GuideManagementDialog(BaseAdminDialog):
    # Сигнал для обновления дерева в главном окне, если структура изменилась
    structure_changed = pyqtSignal() 

    def __init__(self, parent: 'MainWindow'):
        super().__init__(parent)
        self.setWindowTitle("Управление структурой (Admin)")
        self.setMinimumSize(800, 500)
        
        self.setup_ui()
        self.setStyleSheet(DIALOG_STYLE)
        self.load_guides()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Все узлы структуры:"))

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["ID", "Название", "Тип", "Действия"])
        # Настройка размеров колонок
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table)

        layout.addWidget(self.status_label)

        btn_refresh = QPushButton(qta.icon("fa5s.sync", color="#e0e0e0"), "Обновить список")
        btn_refresh.clicked.connect(self.load_guides)
        layout.addWidget(btn_refresh)

    def load_guides(self):
        self.show_loading("Загрузка структуры...")
        self.table.setRowCount(0)
        self.loading_worker = DataLoaderThread(get_structure_metadata)
        self.loading_worker.data_loaded.connect(self.on_guides_loaded)
        self.loading_worker.error_occurred.connect(self.show_error)
        self.loading_worker.start()

    def on_guides_loaded(self, nodes):
        self.hide_loading()
        if not nodes:
            # Пустой список или ошибка
            return

        self.table.setRowCount(len(nodes))
        for row, node in enumerate(nodes):
            self.create_row(row, node)

    def create_row(self, row, node):
        doc_id = node['id']
        title = node['name']
        
        # ID
        id_item = QTableWidgetItem(doc_id)
        id_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        self.table.setItem(row, 0, id_item)
        
        # Title
        self.table.setItem(row, 1, QTableWidgetItem(title))
        
        # Type
        type_item = QTableWidgetItem(node['type'].upper())
        type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 2, type_item)

        # Actions Widget
        actions_widget = QWidget()
        l = QHBoxLayout(actions_widget)
        l.setContentsMargins(2, 2, 2, 2)
        l.setSpacing(4)

        # Rename
        btn_edit = QPushButton(qta.icon("fa5s.edit", color="#e0e0e0"), "")
        btn_edit.setToolTip("Переименовать")
        btn_edit.setFixedSize(30, 30)
        btn_edit.clicked.connect(lambda ch, i=doc_id, t=title: self.rename_node_dialog(i, t))
        
        # Delete
        btn_del = QPushButton(qta.icon("fa5s.trash-alt", color="#ff6b6b"), "")
        btn_del.setToolTip("Удалить")
        btn_del.setFixedSize(30, 30)
        
        if doc_id in ['root_info', 'folder_maps', 'root_settings']:
            btn_del.setEnabled(False)
            btn_edit.setEnabled(False) # Запретим и переименование системных для безопасности
        else:
            btn_del.clicked.connect(lambda ch, i=doc_id, t=title: self.delete_node_confirm(i, t))

        l.addWidget(btn_edit)
        l.addWidget(btn_del)
        l.addStretch()
        
        self.table.setCellWidget(row, 3, actions_widget)

    def rename_node_dialog(self, doc_id, old_title):
        new_title, ok = QInputDialog.getText(self, "Переименование", "Новое имя:", text=old_title)
        if ok and new_title.strip() and new_title != old_title:
            self.show_loading(f"Переименование в {new_title}...")
            self.action_worker = ActionWorkerThread(rename_node, "Успех", "Ошибка переименования", doc_id, new_title.strip())
            self.action_worker.finished.connect(self.on_action_finished)
            self.action_worker.start()

    def delete_node_confirm(self, doc_id, title):
        reply = QMessageBox.question(
            self, "Подтверждение", 
            f"Вы уверены, что хотите удалить '{title}' и все его содержимое?\nЭто действие необратимо.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.show_loading(f"Удаление {title}...")
            self.action_worker = ActionWorkerThread(delete_node_recursively, "Удалено", "Ошибка удаления", doc_id)
            self.action_worker.finished.connect(self.on_action_finished)
            self.action_worker.start()

    def on_action_finished(self, success, message):
        self.hide_loading()
        if success:
            # Обновляем локальный список
            self.load_guides()
            # Сообщаем главному окну (через сигнал)
            self.structure_changed.emit()
        else:
            QMessageBox.critical(self, "Ошибка", message)