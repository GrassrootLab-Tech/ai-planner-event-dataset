from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from utils.logger import logger


class Mongo:
    def __init__(self, uri: str, db_name: str) -> None:
        self._uri = uri
        self._db_name = db_name
        self._client: AsyncIOMotorClient | None = None

    async def connect(self) -> None:
        logger.info("Connecting to MongoDB at %s (db=%s)", self._uri, self._db_name)
        self._client = AsyncIOMotorClient(self._uri)
        logger.info("MongoDB connected")

    async def disconnect(self) -> None:
        if self._client is not None:
            logger.info("Disconnecting from MongoDB")
            self._client.close()
            self._client = None

    @property
    def db(self) -> AsyncIOMotorDatabase:
        if self._client is None:
            raise RuntimeError("Mongo client is not connected. Call connect() first.")
        return self._client[self._db_name]
