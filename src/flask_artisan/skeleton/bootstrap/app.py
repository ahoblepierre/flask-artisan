from pathlib import Path

from flask_artisan import Application

app = Application(Path(__file__).resolve().parent.parent)
