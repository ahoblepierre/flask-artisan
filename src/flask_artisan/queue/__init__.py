"""Files d'attente façon Laravel sur RQ."""

from flask_artisan.queue.jobs import Job
from flask_artisan.queue.manager import QueueManager

__all__ = ["Job", "QueueManager"]
