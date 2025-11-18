# utils/helpers.py
import hashlib
from config import STATIC_SALT 
import sys, os
from pathlib import Path

def resource_path(relative_path):
    """Получает абсолютный путь к ресурсу, независимо от того, запущен ли код через Python или как исполняемый файл PyInstaller."""
    try:
        # PyInstaller создает временную папку и сохраняет путь в _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        # Стандартный режим работы Python
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


def hash_password(password):
    """Хэширует пароль с использованием SHA-256 с солью."""
    salted_password = password + STATIC_SALT
    return hashlib.sha256(salted_password.encode()).hexdigest()