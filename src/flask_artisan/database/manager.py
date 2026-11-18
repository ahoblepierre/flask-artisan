import threading
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import (
    Session,
    configure_mappers,
    scoped_session,
    sessionmaker,
    with_loader_criteria,
)
from sqlalchemy.pool import StaticPool

from flask_artisan.database.connection import EXTRAS, DatabaseError, connection_url


class DatabaseManager:
    """Moteur (créé à la première utilisation) et session courante de l'application."""

    def __init__(self, app):
        self._app = app
        self._engine = None
        self._local = threading.local()
        # expire_on_commit=False : les objets restent lisibles après save() et en fin de requête.
        self._factory = sessionmaker(expire_on_commit=False)
        self._sessions = scoped_session(self._factory)
        event.listen(self._factory, "do_orm_execute", _exclude_trashed)

    @property
    def engine(self):
        if self._engine is None:
            self._engine = self._create_engine()
            self._factory.configure(bind=self._engine)
        return self._engine

    @property
    def session(self) -> Session:
        self.engine  # noqa: B018 — lie le sessionmaker au moteur avant d'ouvrir la session
        return self._sessions()

    def in_transaction(self) -> bool:
        return getattr(self._local, "depth", 0) > 0

    @contextmanager
    def transaction(self):
        """Valide à la sortie, annule sur exception ; un bloc imbriqué rejoint le bloc courant."""
        if self.in_transaction():
            yield
            return
        self._local.depth = 1
        try:
            yield
            self.session.commit()
        except BaseException:
            self.session.rollback()
            raise
        finally:
            self._local.depth = 0

    def create_all(self) -> None:
        from flask_artisan.database.model import Model

        configure_mappers()  # crée les tables pivot de belongs_to_many
        Model.metadata.create_all(self.engine)

    def drop_all(self) -> None:
        from flask_artisan.database.model import Model

        Model.metadata.drop_all(self.engine)

    def remove(self) -> None:
        self._sessions.remove()

    def _create_engine(self):
        config = self._app.make("config")
        name = config.get("database.default")
        conn = config.get(f"database.connections.{name}")
        if not conn:
            raise DatabaseError(f"Connexion '{name}' absente de config/database.py.")
        url = connection_url(conn, self._app.base_path())
        if url.startswith("sqlite:///"):
            # SQLite crée le fichier, pas son dossier.
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        options = {}
        if url == "sqlite://":
            # :memory: : une seule connexion partagée, sinon chaque connexion a sa propre base.
            options = {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
        try:
            return create_engine(url, **options)
        except ImportError as exc:
            extra = EXTRAS.get(conn.get("driver"), conn.get("driver"))
            raise DatabaseError(
                f"Pilote de base manquant pour '{name}' ({exc.name or exc}) : "
                f'installez-le avec pip install "flask-artisan[{extra}]".'
            ) from exc


def _exclude_trashed(state) -> None:
    """Filtre global du soft delete, y compris pour les relations chargées à la demande."""
    if not state.is_select or state.execution_options.get("include_trashed", False):
        return
    from flask_artisan.database.model import SoftDeletes

    state.statement = state.statement.options(
        with_loader_criteria(
            SoftDeletes, lambda cls: cls.deleted_at.is_(None), include_aliases=True
        )
    )
