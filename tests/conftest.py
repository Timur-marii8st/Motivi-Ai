import os
import sys

# Добавляем корень репозитория в sys.path, чтобы импортировать пакет app
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
