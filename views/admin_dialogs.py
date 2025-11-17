# views/admin_dialogs.py
import logging
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QComboBox, QMessageBox, QInputDialog, QLabel, QHeaderView, QWidget
)
from PyQt6.QtCore import Qt, QSize 
from PyQt6.QtGui import QIcon
import qtawesome as qta

from core.firebase_service import (
    get_all_users_firestore, set_user_role_firestore, 
    # Новые функции для работы со структурой
    get_structure_metadata, 
    rename_node,
    delete_node_recursively 
)

if TYPE_CHECKING:
    from views.main_window import MainWindow

# --- ОБЩИЙ СТИЛЬ ДЛЯ ДИАЛОГОВ ---
DIALOG_STYLE = """
    QDialog { background-color: #1a1a1a; color: #e0e0e0; }
    QLabel { color: #e0e0e0; font-size: 14px; margin-bottom: 5px; }
    
    QTableWidget {
        background-color: #232323;
        border: 1px solid #333333;
        color: #e0e0e0;
        gridline-color: #3a3a3a;
        selection-background-color: #00ff85;
        selection-color: black;
        border-radius: 4px;
    }
    QHeaderView::section {
        background-color: #333333;
        color: #e0e0e0;
        padding: 6px;
        border: 1px solid #3a3a3a;
    }
    
    QTableCornerButton::section {
        background-color: #333333;
        border: 1px solid #3a3a3a;
    }
    
    QPushButton {
        background-color: #333333;
        border: 1px solid #4a4a4a;
        padding: 6px 12px;
        border-radius: 4px;
        min-width: 80px;
        color: #e0e0e0;
    }
    QPushButton:hover {
        background-color: #4a4a4a;
    }
    
    QPushButton[icononly="true"] {
        background-color: transparent;
        border: none;
        padding: 0;
    }
    QPushButton[icononly="true"]:hover {
        background-color: #333333;
        border-radius: 2px;
    }
    
    #save_btn {
        background-color: #008f4c;
        border: 1px solid #00ff85;
        color: black;
        font-weight: bold;
    }
    #save_btn:hover {
        background-color: #00ff85;
    }
    
    QComboBox {
        background-color: #2a2a2a;
        border: 1px solid #4a4a4a;
        padding: 4px;
        border-radius: 4px;
        color: #e0e0e0;
    }
    QComboBox::drop-down {
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 15px;
        border-left-width: 1px;
        border-left-color: #4a4a4a;
        border-left-style: solid;
        border-top-right-radius: 3px;
        border-bottom-right-radius: 3px;
    }
    QComboBox::down-arrow {
        image: url(icons/arrow-down.png); /* Заглушка, qtawesome не поддерживается напрямую в стилях QComboBox */
        width: 10px;
        height: 10px;
    }
"""


# --- УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ ---

class UserManagementDialog(QDialog):
    def __init__(self, parent: 'MainWindow'):
        super().__init__(parent)
        self.setWindowTitle("Управление пользователями")
        self.setMinimumSize(600, 400)
        self.parent = parent
        self.users_data = {}

        self.setup_ui()
        self.setStyleSheet(DIALOG_STYLE)
        self.load_users()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        
        main_layout.addWidget(QLabel("Управление ролями пользователей:"))
        
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Логин", "Текущая роль", "Новая роль"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        main_layout.addWidget(self.table)
        
        button_layout = QHBoxLayout()
        self.btn_save = QPushButton(qta.icon("fa5s.save", color="black"), "Сохранить изменения")
        self.btn_save.setObjectName("save_btn")
        self.btn_save.clicked.connect(self.save_changes)
        button_layout.addWidget(self.btn_save)
        
        self.btn_refresh = QPushButton(qta.icon("fa5s.sync", color="#e0e0e0"), "Обновить список")
        self.btn_refresh.clicked.connect(self.load_users)
        button_layout.addWidget(self.btn_refresh)
        
        main_layout.addLayout(button_layout)

    def load_users(self):
        """
        [ИСПРАВЛЕНО] Загружает список пользователей и их ролей.
        Теперь ожидается словарь {login: user_data_dict} от firebase_service.
        """
        
        # 1. Загрузка исходных данных. Ожидаем словарь: {login: {role: '...', ...}}
        self.users_data = get_all_users_firestore()
        self.table.setRowCount(0) # Очистка таблицы
        
        # 2. Проверка типа и обработка ошибки
        if not isinstance(self.users_data, dict):
            logging.error(f"Получен неожиданный формат данных от Firebase: {type(self.users_data)}")
            QMessageBox.critical(self, "Ошибка данных", "Получен неожиданный формат данных от Firebase. Ожидался словарь.")
            return

        # 3. Проверка на пустоту
        if not self.users_data:
            QMessageBox.information(self, "Нет пользователей", "Список пользователей пуст. Проверьте подключение к Firebase или убедитесь, что в базе есть зарегистрированные пользователи.")
            return

        # 4. Заполнение таблицы
        self.table.setRowCount(len(self.users_data))
        roles = ["reader", "editor", "admin"]
        
        for row, (login, data) in enumerate(self.users_data.items()):
            # Теперь data — это словарь с полной информацией о пользователе
            role = data.get('role', 'reader')
            
            # Логин
            login_item = QTableWidgetItem(login)
            login_item.setFlags(login_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, login_item)
            
            # Текущая роль
            role_item = QTableWidgetItem(role.capitalize())
            role_item.setFlags(role_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 1, role_item)
            
            # ComboBox для выбора новой роли
            role_combo = QComboBox()
            role_combo.addItems([r.capitalize() for r in roles])
            role_combo.setCurrentText(role.capitalize())
            
            self.table.setCellWidget(row, 2, role_combo)

        logging.info(f"Загружено {len(self.users_data)} пользователей для управления.")

    def save_changes(self):
        """Сохраняет измененные роли пользователей."""
        changes_made = False
        
        for row in range(self.table.rowCount()):
            login_item = self.table.item(row, 0)
            combo_box = self.table.cellWidget(row, 2)
            
            if login_item and combo_box:
                login = login_item.text()
                new_role = combo_box.currentText().lower()
                current_role = self.users_data.get(login, {}).get('role', 'reader')
                
                if new_role != current_role:
                    if set_user_role_firestore(login, new_role):
                        logging.info(f"Роль пользователя {login} изменена: {current_role} -> {new_role}")
                        changes_made = True
                    else:
                        QMessageBox.critical(self, "Ошибка", f"Не удалось изменить роль для {login}.")
        
        if changes_made:
            QMessageBox.information(self, "Успех", "Изменения ролей успешно сохранены.")
            self.load_users()
        else:
            QMessageBox.information(self, "Сохранение", "Изменений для сохранения не обнаружено.")

# --- УПРАВЛЕНИЕ ГАЙДАМИ ---

class GuideManagementDialog(QDialog):
    def __init__(self, parent: 'MainWindow'):
        super().__init__(parent)
        self.setWindowTitle("Управление гайдами (Структура)")
        self.setMinimumSize(800, 500)
        self.parent = parent

        self.setup_ui()
        self.setStyleSheet(DIALOG_STYLE)
        self.load_guides()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        
        main_layout.addWidget(QLabel("Список всех гайдов (узлов структуры):"))
        
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["ID узла", "Название", "Тип", "Действия"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        main_layout.addWidget(self.table)
        
        button_layout = QHBoxLayout()
        self.btn_refresh = QPushButton(qta.icon("fa5s.sync", color="#e0e0e0"), "Обновить список")
        self.btn_refresh.clicked.connect(self.load_guides)
        button_layout.addWidget(self.btn_refresh)
        
        main_layout.addLayout(button_layout)

    def load_guides(self):
        """Заполняет таблицу текущими гайдами, используя новую структуру."""
        
        # Загружаем все узлы структуры
        all_nodes = get_structure_metadata() 
        
        # Мы показываем все узлы (и папки, и гайды) для удобства управления
        nodes = all_nodes
        
        self.table.setRowCount(len(nodes))

        for row, node in enumerate(nodes):
            doc_id = node['id'] # ID узла структуры
            title = node['name'] # Отображаемое имя
            node_type = node['type']
            
            # ID
            id_item = QTableWidgetItem(doc_id)
            id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, id_item)
            
            # Название
            title_item = QTableWidgetItem(title)
            title_item.setFlags(title_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 1, title_item)

            # Тип
            type_item = QTableWidgetItem(node_type.capitalize())
            type_item.setFlags(type_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 2, type_item)
            
            # Действия
            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(0, 0, 0, 0)
            action_layout.setSpacing(5)
            
            # Кнопка Переименовать
            rename_btn = QPushButton(qta.icon("fa5s.edit", color="#e0e0e0"), "")
            rename_btn.setFixedSize(QSize(30, 30))
            rename_btn.setToolTip("Переименовать узел")
            rename_btn.setProperty("icononly", "true") # Новый property для стилей
            rename_btn.clicked.connect(lambda checked, d=doc_id, t=title: self.rename_node_dialog(d, t))
            action_layout.addWidget(rename_btn)
            
            # Кнопка Удалить
            delete_btn = QPushButton(qta.icon("fa5s.trash-alt", color="#ff6b6b"), "")
            delete_btn.setFixedSize(QSize(30, 30))
            delete_btn.setToolTip("Удалить узел (рекурсивно, включая содержимое)")
            delete_btn.setProperty("icononly", "true") # Новый property для стилей
            
            # Запрет на удаление системных узлов
            if doc_id in ['root_info', 'folder_maps', 'root_settings']:
                delete_btn.setEnabled(False)
                delete_btn.setToolTip("Нельзя удалить базовый системный узел.")
            else:
                delete_btn.clicked.connect(lambda checked, d=doc_id, t=title: self.delete_node(d, t))

            action_layout.addWidget(delete_btn)
            action_layout.addStretch()
            
            self.table.setCellWidget(row, 3, action_widget)
            # Устанавливаем высоту строки, чтобы кнопки выглядели лучше
            self.table.setRowHeight(row, 35) 

        logging.info(f"Загружено {len(nodes)} узлов структуры гайдов.")

    def rename_node_dialog(self, doc_id: str, old_title: str):
        """Диалог переименования узла."""
        # Проверка, уже выполнена в parent.rename_node_dialog, но повторим для безопасности
        if doc_id in ['root_info', 'folder_maps', 'root_settings']:
             QMessageBox.warning(self, "Ошибка", f"Нельзя переименовать базовый узел '{old_title}'.")
             return

        new_title, ok = QInputDialog.getText(self, "Переименовать узел", "Введите новое название:", text=old_title)
        if ok and new_title.strip() and new_title != old_title:
            if rename_node(doc_id, new_title.strip()):
                QMessageBox.information(self, "Успех", f"Узел '{old_title}' переименован в '{new_title.strip()}'")
                self.load_guides()
            else:
                QMessageBox.critical(self, "Ошибка", "Не удалось переименовать узел.")
                
    def delete_node(self, doc_id: str, title: str):
        """Вызывает рекурсивное удаление через MainWindow (для подтверждения)."""
        
        # Используем метод родителя, который включает диалог подтверждения
        if self.parent.delete_node_dialog(doc_id, title): 
            self.load_guides()