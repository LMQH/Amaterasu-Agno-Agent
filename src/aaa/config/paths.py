"""应用家目录与文件布局。路径与文件位置只在这里定义。"""

from pathlib import Path

HOME_DIR = Path.home() / ".aaa"
DATA_DIR = HOME_DIR / "data"
LOG_DIR = HOME_DIR / "logs"
DB_FILE = DATA_DIR / "sessions.db"
USAGE_FILE = DATA_DIR / "usage.db"
LOG_FILE = LOG_DIR / "aaa.log"
SECRET_FILE = HOME_DIR / "secret.yaml"
CONFIG_FILE = HOME_DIR / "config.toml"
HISTORY_FILE = HOME_DIR / "history"
