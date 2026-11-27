import textwrap

import pytest

from flask_artisan.application import Application


@pytest.fixture
def scheduled(make_project):
    """Écrit routes/console.py, crée l'app et charge le planning."""

    def _make(source: str = "", **overrides) -> Application:
        root = make_project(**overrides)
        (root / "routes").mkdir(exist_ok=True)
        path = root / "routes" / "console.py"
        path.write_text(textwrap.dedent(source))
        app = Application(root)
        app.make("schedule").load(path)
        return app

    return _make
