import re

import pytest
from sqlalchemy import Column, String, inspect

from flask_artisan import DB

MODEL = """from flask_artisan.database import Mapped, Model


class MigNote(Model):
    body: Mapped[str]
"""


@pytest.fixture
def project(db_app, tmp_path, monkeypatch):
    root = tmp_path
    (root / "app" / "models").mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("")
    (root / "app" / "models" / "__init__.py").write_text("")
    (root / "app" / "models" / "mig_note.py").write_text(MODEL)
    monkeypatch.syspath_prepend(str(root))
    # Le module app.models.mig_note reste en cache d'un test à l'autre : MigNote n'est
    # déclaré qu'une fois (registre SQLAlchemy global).
    app = db_app(database="database/test.sqlite")
    app.make("db").drop_all()  # base vide : les tables viennent des migrations
    return app


def run(app, *args):
    result = app.test_cli_runner().invoke(args=list(args))
    assert result.exit_code == 0, result.output
    return result.output


def migrations(app):
    return sorted(p.name for p in app.base_path("database/migrations").glob("*.py"))


def has_table(name):
    return inspect(DB.engine).has_table(name)


def test_make_migration_creates_file(project):
    out = run(project, "make:migration", "create notes")
    files = migrations(project)
    assert len(files) == 1
    assert re.fullmatch(r"\d{4}_\d{2}_\d{2}_\d{6}_create_notes\.py", files[0])
    assert files[0] in out
    assert "create_table" in (project.base_path("database/migrations") / files[0]).read_text()


def test_make_migration_no_changes(project):
    run(project, "make:migration", "create notes")
    run(project, "migrate")
    out = run(project, "make:migration", "nothing")
    assert "Aucun changement" in out and len(migrations(project)) == 1


def test_migrate_status_rollback(project):
    run(project, "make:migration", "create notes")
    assert "[ ]" in run(project, "migrate:status")
    run(project, "migrate")
    assert has_table("mig_notes")
    assert "[x]" in run(project, "migrate:status")
    run(project, "migrate:rollback")
    assert not has_table("mig_notes")


def test_sqlite_alter_in_batch(project):
    from app.models.mig_note import MigNote

    run(project, "make:migration", "create notes")
    run(project, "migrate")
    extra = Column("extra", String, nullable=False, server_default="x")
    MigNote.__table__.append_column(extra)
    try:
        run(project, "make:migration", "add extra")
        latest = (
            project.base_path("database/migrations")
            / next(f for f in migrations(project) if "add_extra" in f)
        ).read_text()
        assert "batch_alter_table" in latest
        run(project, "migrate")
        assert "extra" in [c["name"] for c in inspect(DB.engine).get_columns("mig_notes")]
        run(project, "migrate:rollback")
        assert "extra" not in [c["name"] for c in inspect(DB.engine).get_columns("mig_notes")]
    finally:
        MigNote.__table__._columns.remove(extra)
