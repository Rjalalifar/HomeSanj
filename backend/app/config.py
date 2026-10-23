"""Environment configuration; credentials are never serialized into API responses."""
import os
from dataclasses import dataclass
from dotenv import load_dotenv


@dataclass
class Settings:
    database_url: str = 'sqlite:///./runtime/khanehsanj.sqlite3'
    data_dir: str = './data'
    batch_limit: int = 30
    cache_ttl: int = 3600

    @classmethod
    def from_env(cls):
        load_dotenv()
        return cls(database_url=os.getenv('DATABASE_URL') or ('sqlite:///' + os.environ['SQLITE_DB_PATH'] if os.getenv('SQLITE_DB_PATH') else cls.database_url),
                   data_dir=os.getenv('DATA_DIR', cls.data_dir),
                   batch_limit=max(1, min(100, int(os.getenv('ROUTING_BATCH_LIMIT', '30')))),
                   cache_ttl=max(1, int(os.getenv('ROUTING_CACHE_TTL_SECONDS', '3600'))))
