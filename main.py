# main.py
import sys
import logging
from PyQt6.QtWidgets import QApplication, QDialog

# Импорты из нашего проекта
import config 
from core.firebase_service import init_firebase, ensure_initial_guides
from views.auth_dialogs import LoginDialog
from views.main_window import MainWindow

def main():
    """Главная функция запуска приложения."""
    
    # 1. Инициализируем Firebase
    if init_firebase():
        ensure_initial_guides()
    else:
        logging.critical("Критическая ошибка: не удалось инициализировать Firebase. Выход.")
        sys.exit(1)

    # 2. Запускаем GUI
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # Устанавливаем, что приложение НЕ должно завершаться, когда главное окно закрывается
    app.setQuitOnLastWindowClosed(False) 
    
    login = LoginDialog()
    
    # Флаг, чтобы выйти из цикла после успешного запуска MainWindow
    main_window_launched = False 

    # 🔥 ИСПРАВЛЕНИЕ: Запускаем цикл только до первого успешного входа или отмены
    while not main_window_launched:
        
        if login.exec() == QDialog.DialogCode.Accepted:
            # 3. Если вход успешен
            username = login.login_edit.text().strip() or "Гость"
            role = login.get_role()
            
            # Передаем LoginDialog в MainWindow
            win = MainWindow(username, role, parent=login) 
            win.show()
            
            # 🔥 Устанавливаем флаг, чтобы выйти из цикла и перейти к app.exec()
            main_window_launched = True 
            
        else:
            # Если диалог входа отменен, выходим из цикла
            break
            
    # 4. Запускаем главный цикл событий только ОДИН РАЗ
    if main_window_launched:
        sys.exit(app.exec())
    else:
        # Если пользователь отменил вход на первом шаге
        sys.exit(0)
        
if __name__ == '__main__':
    config.setup_logging()
    main()