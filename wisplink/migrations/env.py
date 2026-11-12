from alembic import context

from wisplink.config import Settings
from wisplink.db import database, metadata

engine = database(Settings.from_env())
with engine.connect() as connection:
    connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    connection.commit()
    context.configure(connection=connection, target_metadata=metadata)
    with context.begin_transaction():
        context.run_migrations()
