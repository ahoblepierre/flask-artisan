"""Environnement Alembic fourni par Flask-Artisan : le projet n'a ni alembic.ini ni env.py."""

from alembic import context
from sqlalchemy.orm import configure_mappers

from flask_artisan.database.model import Model

config = context.config
app = config.attributes["app"]
configure_mappers()  # tables pivot de belongs_to_many dans les métadonnées

with app.make("db").engine.connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=Model.metadata,
        # SQLite ne sait pas modifier une colonne : Alembic recrée la table (mode batch).
        render_as_batch=connection.dialect.name == "sqlite",
        process_revision_directives=config.attributes.get("process_revision_directives"),
    )
    with context.begin_transaction():
        context.run_migrations()
