# main.py
import sys
import logging
from PyQt6.QtWidgets import QApplication, QDialog

# Импорты из нашего проекта
import config 
from core.firebase_service import init_firebase, ensure_initial_guides
from views.auth_dialogs import LoginDialog
from views.main_window import MainWindow
from utils.helpers import resource_path

# --- Новая функция для создания и запуска главного окна ---
def launch_main_window(login_dialog: LoginDialog):
    """Создает и показывает MainWindow после успешного входа."""
    username = login_dialog.login_edit.text().strip() or "Гость"
    role = login_dialog.get_role()
    
    # 1. Скрываем диалог входа (это тот экземпляр, который только что запустили модально)
    login_dialog.hide() 
    
    # 2. Создаем и показываем главное окно
    # Передаем ссылку на LoginDialog для обратного вызова при logout
    win = MainWindow(username, role, parent=login_dialog) 
    win.show()
    
    return win 

def main():
    """Главная функция запуска приложения."""
    
    # 1. Инициализируем Firebase
    if not init_firebase():
        logging.critical("Критическая ошибка: не удалось инициализировать Firebase. Выход.")
        sys.exit(1)
    ensure_initial_guides()

    # 2. Запускаем GUI
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # Устанавливаем, что приложение НЕ должно завершаться, когда главное окно закрывается
    app.setQuitOnLastWindowClosed(False) 
    
    # 🔥 ЦИКЛ ДЛЯ ПЕРЕЗАПУСКА (login -> app -> logout -> login)
    while True:
        login = LoginDialog()
        
        # Запускаем LoginDialog модально
        result = login.exec() 
        
        if result == QDialog.DialogCode.Accepted:
            # Успешный вход: запускаем главное окно
            main_window = launch_main_window(login)
            
            # 3. Запускаем главный цикл событий.
            # Он будет работать до тех пор, пока не будет вызван QApplication.exit() из logout().
            app.exec()
            
            # После выхода из app.exec(), мы возвращаемся в начало цикла while True
            # и создаем новый LoginDialog
            
        else:
            # Отмена входа или закрытие окна логина: выходим из приложения
            sys.exit(0)      
if __name__ == '__main__':
    config.setup_logging()
    main()