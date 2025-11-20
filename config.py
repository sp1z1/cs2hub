# config.py
import sys
import logging
import logging.handlers 
from pathlib import Path

# ===================== ПУТИ И ЛОГИ =====================
BASE_DIR = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
(IMAGES_DIR := DATA_DIR / "images").mkdir(exist_ok=True)
(BACKUP_DIR := DATA_DIR / "backups").mkdir(exist_ok=True)
(LOGS_DIR := DATA_DIR / "logs").mkdir(exist_ok=True)

def setup_logging():
    """Настраивает ротируемое логирование для файла и консоли."""
    log_file = LOGS_DIR / "app.log"

    # Основной логгер приложения
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)  # Логгер принимает все уровни

    # --- Файл (все DEBUG и выше) ---
    file_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(filename)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)

    # --- Консоль (INFO и выше) ---
    console_formatter = logging.Formatter("%(levelname)-8s | %(message)s")
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(logging.INFO)  # INFO+ в консоль
    logger.addHandler(console_handler)

# ===================== КОНСТАНТЫ FIREBASE =====================
CRED_PATH = BASE_DIR / "firebase_creds.json"
FIREBASE_STORAGE_BUCKET = "gs://cs2-guide-hub.appspot.com"

# ===================== КОНСТАНТЫ ПРИЛОЖЕНИЯ ====================
STATIC_SALT = "cs2_guide_hub_salt" 
APP_VERSION = "Beta 0.5"
DEFAULT_GUIDE_CONTENT = lambda title: f"# {title}\n\nНачните писать гайд здесь."