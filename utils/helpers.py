# utils/helpers.py
import hashlib
from config import STATIC_SALT 
import sys
from pathlib import Path

def resource_path(rel):
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / rel
    return Path(rel)

def hash_password(password):
    """Хэширует пароль с использованием SHA-256 с солью."""
    salted_password = password + STATIC_SALT
    return hashlib.sha256(salted_password.encode()).hexdigest()

# path_to_doc_id удален