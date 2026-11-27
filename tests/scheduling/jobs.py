from pathlib import Path

from flask_artisan import base_path
from flask_artisan.queue import Job


class SRSync(Job):
    """Job importable (un job défini dans routes/console.py ne l'est pas)."""

    def handle(self):
        with Path(base_path("routes/log.txt")).open("a") as f:
            f.write("handled\n")
