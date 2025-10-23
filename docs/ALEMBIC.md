This project uses SQLModel (SQLAlchemy) and an async engine. Alembic is configured to read the database URL from `app.config.settings.DATABASE_URL` and to use `SQLModel.metadata` for autogeneration.

Common commands (run from project root):

# Create a new revision with autogenerate
alembic revision --autogenerate -m "describe change"

# Apply migrations
alembic upgrade head

# Downgrade (example)
alembic downgrade -1

Notes:
- The alembic `env.py` uses the project's settings to construct the async engine and will import model modules so autogenerate can see them.
- For the first baseline migration, run:
  alembic revision --autogenerate -m "baseline"
  and then `alembic upgrade head` to apply it.

If you run into import errors when Alembic imports app modules, ensure your PYTHONPATH includes the project root or run Alembic from the project root with the virtualenv activated.