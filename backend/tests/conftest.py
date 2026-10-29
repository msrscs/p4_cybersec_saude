import os

# Valor fictício apenas para os testes; nenhum banco é acessado nesta fase.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
