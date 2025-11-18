# views/auth_dialogs.py
import re, logging
import qtawesome as qta
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QLabel, 
    QPushButton, QMessageBox, QVBoxLayout, QFrame, QHBoxLayout
)
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt, QTimer, QSize

# Импорты из нашего проекта
from utils.helpers import hash_password
from core.firebase_service import register_user_firestore, get_user_role_firestore

class RegisterDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Регистрация")
        self.setWindowIcon(qta.icon("fa5s.user-plus", color="#00ff85"))
        self.layout = QFormLayout(self)
        self.layout.setContentsMargins(30, 30, 30, 30)

        self.login = QLineEdit()
        self.pwd1 = QLineEdit()
        self.pwd2 = QLineEdit()
        self.pwd1.setEchoMode(QLineEdit.EchoMode.Password)
        self.pwd2.setEchoMode(QLineEdit.EchoMode.Password)
        
        # Новый стиль: добавление иконок в поля
        self._setup_icon(self.login, "user")
        self._setup_icon(self.pwd1, "lock")
        self._setup_icon(self.pwd2, "lock")


        self.layout.addRow("Логин:", self.login)
        
        self.login_error_label = QLabel("")
        self.login_error_label.setObjectName("errorLabel")
        self.layout.addRow(self.login_error_label)
        
        self.layout.addRow("Пароль:", self.pwd1)
        self.layout.addRow("Повтор:", self.pwd2)
        
        self.pwd_error_label = QLabel("")
        self.pwd_error_label.setObjectName("errorLabel")
        self.layout.addRow(self.pwd_error_label)
        
        self.login.textChanged.connect(self.validate_login_live)
        self.pwd1.textChanged.connect(self.validate_password_live)
        self.pwd2.textChanged.connect(self.validate_password_live)

        self.register_btn = QPushButton("Зарегистрироваться")
        self.register_btn.setObjectName("main_btn")
        self.register_btn.clicked.connect(self.register)
        self.layout.addRow(self.register_btn)
        
        self.setStyleSheet(self._get_style_sheet())
        
        self.setFixedSize(360, 350)

    def _get_style_sheet(self):
        return """
            QDialog { background-color: #1a1a1a; color: #e0e0e0; border-radius: 8px; }
            QLabel { color: #e0e0e0; font-size: 14px; }
            QLabel#errorLabel { color: #ff6b6b; font-size: 12px; padding: 2px 0; }
            
            QLineEdit { 
                background: #232323; 
                border: 1px solid #333333; 
                color: #e0e0e0; 
                padding: 7px 10px; 
                border-radius: 6px; 
                padding-left: 35px; /* Для иконки */
            }
            QLineEdit:focus {
                border-color: #00ff85;
            }
            
            QPushButton {
                background: #232323;
                border: 1px solid #333333;
                color: #e0e0e0;
                border-radius: 6px;
                padding: 8px 15px;
                min-height: 25px;
                font-weight: 500;
            }
            QPushButton:hover {
                border-color: #00ff85;
                background: #2a2a2a;
            }
            
            QPushButton#main_btn { 
                background: #00ff85;
                color: black;
                font-weight: bold;
                border: 1px solid #00ff85;
            }
            QPushButton#main_btn:hover {
                 background: #00d970;
            }
        """

    def _setup_icon(self, line_edit, icon_name):
        # Вставляет иконку в QLineEdit
        icon_label = QLabel(line_edit)
        icon_label.setPixmap(qta.icon(f"fa5s.{icon_name}", color="#666666").pixmap(QSize(18, 18)))
        icon_label.setGeometry(8, (line_edit.height() - 18) // 2, 18, 18)

    def validate_login_live(self):
        login_text = self.login.text().strip()
        self.login_error_label.setText("") 
        
        if not login_text:
            return False
            
        if not re.match(r"^[a-zA-Z0-9]{1,20}$", login_text):
            self.login_error_label.setText("Латинские буквы/цифры, макс. 20 символов.")
            return False
            
        return True

    def validate_password_live(self):
        pwd1_text = self.pwd1.text()
        pwd2_text = self.pwd2.text()
        self.pwd_error_label.setText("") 
        self.pwd_error_label.setStyleSheet("color: #ff6b6b; font-size: 12px;")
        
        is_valid = True

        if len(pwd1_text) < 5:
            self.pwd_error_label.setText("Мин. 5 символов.")
            is_valid = False
        elif not re.search(r"[a-zA-Z]", pwd1_text):
            self.pwd_error_label.setText("Должен содержать латинские буквы.")
            is_valid = False
        elif not re.search(r"\d", pwd1_text):
            self.pwd_error_label.setText("Должен содержать хотя бы одну цифру.")
            is_valid = False
        elif pwd1_text != pwd2_text:
            self.pwd_error_label.setText("Пароли не совпадают.")
            is_valid = False
        
        if is_valid and pwd1_text and pwd2_text:
            self.pwd_error_label.setText("✅ Пароли совпадают")
            self.pwd_error_label.setStyleSheet("color: #00ff85; font-size: 12px;")
            # Убираем временное изменение цвета, возвращая стандартный стиль через 2 сек
            QTimer.singleShot(2000, lambda: self.pwd_error_label.setStyleSheet(self._get_style_sheet() + "QLabel#errorLabel { color: #ff6b6b; }")) 
            
        return is_valid

    def register(self):
        login_text = self.login.text().strip()
        pwd1_text = self.pwd1.text()
        pwd2_text = self.pwd2.text()
        
        login_ok = self.validate_login_live()
        pwd_ok = self.validate_password_live()

        if not login_text or not pwd1_text or not pwd2_text:
            QMessageBox.warning(self, "Ошибка", "Все поля должны быть заполнены.")
            return
            
        if not login_ok or not pwd_ok:
            return 

        password_hash = hash_password(pwd1_text) 

        if register_user_firestore(login_text, password_hash):
            QMessageBox.information(self, "Готово", "Аккаунт создан! Теперь войдите.")
            self.accept()
        else:
            QMessageBox.warning(self, "Ошибка", "Логин занят или ошибка регистрации.")
            self.login.setFocus()


class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Вход в CS2 Guide Hub")
        self.setWindowIcon(qta.icon("fa5s.crosshairs", color="#00ff85"))
        self.role = "user"

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(50, 50, 50, 50)
        main_layout.setSpacing(15)
        
        title = QLabel("Вход")
        title.setFont(QFont("Segoe UI", 28))
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title)
        
        logo_label = QLabel()
        logo_label.setPixmap(qta.icon("fa5s.user-ninja", color="#00ff85").pixmap(QSize(64, 64)))
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(logo_label)

        form_frame = QFrame()
        form_layout = QFormLayout(form_frame)
        form_layout.setSpacing(15)
        form_layout.setContentsMargins(0, 10, 0, 10)

        self.login_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)

        self._setup_icon(self.login_edit, "user")
        self._setup_icon(self.password_edit, "lock")
        
        self.login_edit.setPlaceholderText("Имя пользователя")
        self.password_edit.setPlaceholderText("Пароль")

        self.login_error_label = QLabel("") 
        self.login_error_label.setObjectName("errorLabel")
        
        self.pwd_error_label = QLabel("")
        self.pwd_error_label.setObjectName("errorLabel")
        
        login_vbox = QVBoxLayout()
        login_vbox.setContentsMargins(0, 0, 0, 0)
        login_vbox.setSpacing(2) 
        login_vbox.addWidget(self.login_edit)
        login_vbox.addWidget(self.login_error_label)
        
        # Убраны заголовки "Логин" и "Пароль" для минимализма
        form_layout.addRow(login_vbox) 

        password_vbox = QVBoxLayout()
        password_vbox.setContentsMargins(0, 0, 0, 0)
        password_vbox.setSpacing(2)
        password_vbox.addWidget(self.password_edit)
        password_vbox.addWidget(self.pwd_error_label)
        
        form_layout.addRow(password_vbox)
        
        main_layout.addWidget(form_frame)

        self.login_btn = QPushButton("Войти")
        self.login_btn.setObjectName("login_btn")
        self.login_btn.clicked.connect(self.login)
        main_layout.addWidget(self.login_btn)

        self.register_btn = QPushButton("Зарегистрироваться")
        self.register_btn.clicked.connect(self.open_register_dialog)
        main_layout.addWidget(self.register_btn)
        
        self.setStyleSheet(self.get_style_sheet())
        
        self.login_edit.textChanged.connect(self.validate_login_live)
        self.password_edit.textChanged.connect(self.clear_password_error)

        self.login_edit.setFocus()
        self.login_edit.returnPressed.connect(self.login)
        self.password_edit.returnPressed.connect(self.login)
        
        self.setFixedSize(450, 500)
        

    def get_style_sheet(self):
        return """
            QDialog {
                background: #1a1a1a;
                color: #e0e0e0;
                border: 1px solid #333333;
                border-radius: 10px;
            }
            QLabel {
                font-size: 16px;
                color: #e0e0e0;
            }
            QLabel#titleLabel {
                color: #00ff85;
                font-weight: bold;
                margin-bottom: 5px;
            }
            QLabel#errorLabel {
                color: #ff6b6b; 
                font-size: 12px;
            }
            QLineEdit {
                background: #232323; 
                border: 1px solid #333333;
                border-radius: 6px;
                padding: 10px 10px;
                padding-left: 40px; 
                color: #e0e0e0;
                font-size: 14px;
            }
            QLineEdit:focus {
                border-color: #00ff85;
            }
            
            QPushButton {
                background: #232323;
                border: 1px solid #333333;
                color: #e0e0e0;
                border-radius: 6px;
                padding: 10px 15px;
                min-height: 25px;
                font-weight: 500;
            }
            QPushButton:hover {
                border-color: #00ff85;
                background: #2a2a2a;
                color: #ffffff;
            }
            #login_btn { 
                background: #00ff85;
                color: black;
                font-weight: bold;
                border: 1px solid #00ff85;
            }
            #login_btn:hover {
                 background: #00d970;
            }
        """

    def _setup_icon(self, line_edit, icon_name):
        # Вставляет иконку в QLineEdit
        icon_label = QLabel(line_edit)
        icon_label.setPixmap(qta.icon(f"fa5s.{icon_name}", color="#666666").pixmap(QSize(20, 20)))
        # Вычисляем позицию для центрирования по вертикали
        icon_label.setGeometry(10, 10, 20, 20)
        
    def open_register_dialog(self):
        register_dialog = RegisterDialog(self)
        register_dialog.exec()

    def validate_login_live(self):
        login_text = self.login_edit.text().strip()
        self.login_error_label.setText("")
        
        if login_text and not re.match(r"^[a-zA-Z0-9]{1,20}$", login_text):
            self.login_error_label.setText("Только латинские буквы/цифры, макс. 20 символов.")
            return False
            
        return True
        
    def clear_password_error(self):
        self.pwd_error_label.setText("")
        
    def login(self):
        login_text = self.login_edit.text().strip()
        password_text = self.password_edit.text()
        
        self.login_error_label.setText("")
        self.pwd_error_label.setText("")
        
        if not login_text or not password_text:
            QMessageBox.warning(self, "Ошибка", "Введите логин и пароль.")
            return
            
        if not self.validate_login_live():
            return

        password_hash = hash_password(password_text)

        result = get_user_role_firestore(login_text, password_hash)
        
        if isinstance(result, str) and result not in ('Неверный_пароль', 'Пользователя_не_существует'):
            self.role = result
            self.accept()
        elif result == 'Неверный_пароль':
            self.pwd_error_label.setText("Неверный пароль")
            self.password_edit.setFocus()
        elif result == 'Пользователя_не_существует':
            self.login_error_label.setText("Пользователя не существует")
            self.login_edit.setFocus()
        else:
            QMessageBox.critical(self, "Ошибка", "Не удалось подключиться к базе данных.")

    def get_role(self):
        return self.role