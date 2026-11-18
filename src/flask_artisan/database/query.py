from werkzeug.exceptions import NotFound


class ModelNotFound(NotFound):
    """Levée par find_or_fail / first_or_fail : une 404 pendant une requête."""
