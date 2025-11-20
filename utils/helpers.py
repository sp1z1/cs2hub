# utils/helpers.py
import bcrypt
import sys
import os
from pathlib import Path

def resource_path(relative_path):
    """Получает абсолютный путь к ресурсу, работает с PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def hash_password(password: str) -> str:
    """Безопасное хэширование пароля с помощью bcrypt."""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode('utf-8')


def check_password(password: str, hashed: str) -> bool:
    """Проверка пароля против хэша."""
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))