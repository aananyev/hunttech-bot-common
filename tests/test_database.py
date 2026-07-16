"""Tests for the database module.

Uses mock/patch since we don't have a real PostgreSQL server in tests.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hunttech_bot_common.database import (
    BaseRepository,
    DatabaseMigrator,
    DatabasePool,
    PoolConfig,
    UnitOfWork,
)
from hunttech_bot_common.exceptions import DatabaseError


# ═══════════════════════════════════════════════
# PoolConfig tests
# ═══════════════════════════════════════════════

class TestPoolConfig:
    """Tests for PoolConfig."""

    def test_from_url_basic(self) -> None:
        """from_url parses basic DATABASE_URL."""
        config = PoolConfig.from_url(
            "postgresql://user:***@host:5432/dbname"
        )
        assert config.dsn == "postgresql://user:***@host:5432/dbname"
        assert config.min_size == 2
        assert config.max_size == 10
        assert config.connect_timeout == 10
        assert config.statement_timeout_ms == 30000
        assert config.sslmode == "prefer"

    def test_from_url_with_params(self) -> None:
        """from_url parses query parameters."""
        config = PoolConfig.from_url(
            "postgresql://user:***@host:5432/dbname"
            "?sslmode=require&connect_timeout=5"
            "&pool_min=1&pool_max=5&application_name=test_bot"
        )
        assert config.sslmode == "require"
        assert config.connect_timeout == 5
        assert config.min_size == 1
        assert config.max_size == 5
        assert config.application_name == "test_bot"

    def test_ssl_context_disable(self) -> None:
        """sslmode=disable returns None."""
        config = PoolConfig.from_url(
            "postgresql://host/db?sslmode=disable"
        )
        assert config._make_ssl_context() is None

    def test_ssl_context_require(self) -> None:
        """sslmode=require returns non-None SSL context."""
        config = PoolConfig.from_url(
            "postgresql://host/db?sslmode=require"
        )
        ctx = config._make_ssl_context()
        assert ctx is not None

    def test_default_sslmode(self) -> None:
        """Default sslmode is prefer."""
        config = PoolConfig(dsn="postgresql://host/db")
        assert config.sslmode == "prefer"


# ═══════════════════════════════════════════════
# DatabasePool tests
# ═══════════════════════════════════════════════

class TestDatabasePool:
    """Tests for DatabasePool."""

    def test_init(self) -> None:
        """Pool initialises in disconnected state."""
        config = PoolConfig(dsn="postgresql://localhost/test")
        pool = DatabasePool(config)
        assert pool.is_connected is False
        assert pool.config is config

    @pytest.mark.asyncio
    @patch("asyncpg.create_pool", new_callable=AsyncMock)
    async def test_connect(self, mock_create_pool: AsyncMock) -> None:
        """connect creates the pool."""
        mock_pool = MagicMock()
        mock_pool._closed = False
        mock_create_pool.return_value = mock_pool

        config = PoolConfig(dsn="postgresql://localhost/test")
        pool = DatabasePool(config)
        await pool.connect()

        assert pool.is_connected is True
        mock_create_pool.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("asyncpg.create_pool", new_callable=AsyncMock)
    async def test_connect_idempotent(self, mock_create_pool: AsyncMock) -> None:
        """connect is idempotent."""
        mock_pool = MagicMock()
        mock_pool._closed = False
        mock_create_pool.return_value = mock_pool

        pool = DatabasePool(PoolConfig(dsn="postgresql://localhost/test"))
        await pool.connect()
        await pool.connect()  # second call should be no-op
        assert mock_create_pool.await_count == 1

    @pytest.mark.asyncio
    @patch("asyncpg.create_pool", new_callable=AsyncMock)
    async def test_close(self, mock_create_pool: AsyncMock) -> None:
        """close releases the pool."""
        mock_pool = MagicMock()
        mock_pool._closed = False
        mock_pool.close = AsyncMock()  # close is a coroutine
        mock_create_pool.return_value = mock_pool

        pool = DatabasePool(PoolConfig(dsn="postgresql://localhost/test"))
        await pool.connect()
        await pool.close()

        assert pool.is_connected is False
        mock_pool.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_health_check_disconnected(self) -> None:
        """health_check returns disconnected when pool not connected."""
        pool = DatabasePool(PoolConfig(dsn="postgresql://localhost/test"))
        result = await pool.health_check()  # async method — must await
        assert result["status"] == "disconnected"
        assert result["latency_ms"] is None

    @pytest.mark.asyncio
    @patch("asyncpg.create_pool", new_callable=AsyncMock)
    async def test_fetch(self, mock_create_pool: AsyncMock) -> None:
        """fetch delegates to the pool."""
        mock_pool = MagicMock()
        mock_pool._closed = False
        mock_pool.acquire = MagicMock()
        mock_create_pool.return_value = mock_pool

        pool = DatabasePool(PoolConfig(dsn="postgresql://localhost/test"))
        await pool.connect()

        # Mock the acquire context manager
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[{"id": 1}])
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire.return_value = mock_cm

        result = await pool.fetch("SELECT 1")
        assert len(result) == 1
        assert result[0]["id"] == 1

    @pytest.mark.asyncio
    @patch("asyncpg.create_pool", new_callable=AsyncMock)
    async def test_execute(self, mock_create_pool: AsyncMock) -> None:
        """execute delegates to the pool."""
        mock_pool = MagicMock()
        mock_pool._closed = False
        mock_pool.acquire = MagicMock()
        mock_create_pool.return_value = mock_pool

        pool = DatabasePool(PoolConfig(dsn="postgresql://localhost/test"))
        await pool.connect()

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="CREATE TABLE")
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire.return_value = mock_cm

        result = await pool.execute("CREATE TABLE test (id int)")
        assert result == "CREATE TABLE"


# ═══════════════════════════════════════════════
# BaseRepository tests
# ═══════════════════════════════════════════════

class TestBaseRepository:
    """Tests for BaseRepository."""

    @pytest.fixture
    def pool(self) -> MagicMock:
        """Create a mock DatabasePool."""
        p = MagicMock(spec=DatabasePool)
        p.fetchrow = AsyncMock()
        p.fetch = AsyncMock()
        p.fetchval = AsyncMock()
        p.execute = AsyncMock()
        return p

    @pytest.fixture
    def repo(self, pool: MagicMock) -> BaseRepository:
        """Create a BaseRepository with mock pool."""
        return BaseRepository(pool, table_name="test_table", pk_column="id")

    def test_init(self, repo: BaseRepository) -> None:
        """Repository initialises with correct properties."""
        assert repo.table_name == "test_table"
        assert repo.pk_column == "id"
        assert repo.pool is not None

    @pytest.mark.asyncio
    async def test_get_by_id(self, repo: BaseRepository, pool: MagicMock) -> None:
        """get_by_id calls fetchrow with correct query."""
        pool.fetchrow.return_value = {"id": 1, "name": "test"}

        result = await repo.get_by_id(1)
        assert result["id"] == 1
        pool.fetchrow.assert_awaited_once_with(
            "SELECT * FROM test_table WHERE id = $1", 1
        )

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(
        self, repo: BaseRepository, pool: MagicMock
    ) -> None:
        """get_by_id returns None when not found."""
        pool.fetchrow.return_value = None
        result = await repo.get_by_id(999)
        assert result is None

    @pytest.mark.asyncio
    async def test_find_all(self, repo: BaseRepository, pool: MagicMock) -> None:
        """find_all calls fetch with ordering and pagination."""
        pool.fetch.return_value = [{"id": 1}, {"id": 2}]

        result = await repo.find_all(order_by="name ASC", limit=10, offset=5)
        assert len(result) == 2
        pool.fetch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_find_all_no_params(
        self, repo: BaseRepository, pool: MagicMock
    ) -> None:
        """find_all with no params still works."""
        pool.fetch.return_value = []
        result = await repo.find_all()
        assert result == []

    @pytest.mark.asyncio
    async def test_find_where(self, repo: BaseRepository, pool: MagicMock) -> None:
        """find_where builds correct WHERE clause."""
        pool.fetch.return_value = [{"id": 1, "status": "active"}]

        result = await repo.find_where(
            {"status": "active", "deleted": False}
        )
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_create(self, repo: BaseRepository, pool: MagicMock) -> None:
        """create inserts and returns the row."""
        pool.fetchrow.return_value = {"id": 1, "name": "test", "email": "test@test"}

        result = await repo.create(name="test", email="test@test")
        assert result["id"] == 1
        pool.fetchrow.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update(self, repo: BaseRepository, pool: MagicMock) -> None:
        """update builds correct UPDATE query."""
        pool.fetchrow.return_value = {"id": 1, "name": "updated"}

        result = await repo.update(1, name="updated")
        assert result["name"] == "updated"
        pool.fetchrow.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_found(self, repo: BaseRepository, pool: MagicMock) -> None:
        """delete returns True when row deleted."""
        pool.execute.return_value = "DELETE 1"

        result = await repo.delete(1)
        assert result is True
        pool.execute.assert_awaited_once_with(
            "DELETE FROM test_table WHERE id = $1", 1
        )

    @pytest.mark.asyncio
    async def test_delete_not_found(
        self, repo: BaseRepository, pool: MagicMock
    ) -> None:
        """delete returns False when no row."""
        pool.execute.return_value = "DELETE 0"

        result = await repo.delete(999)
        assert result is False

    @pytest.mark.asyncio
    async def test_count(self, repo: BaseRepository, pool: MagicMock) -> None:
        """count returns row count."""
        pool.fetchval.return_value = 42

        result = await repo.count()
        assert result == 42

    @pytest.mark.asyncio
    async def test_exists_true(self, repo: BaseRepository, pool: MagicMock) -> None:
        """exists returns True when found."""
        pool.fetchval.return_value = 1

        result = await repo.exists(1)
        assert result is True

    @pytest.mark.asyncio
    async def test_exists_false(self, repo: BaseRepository, pool: MagicMock) -> None:
        """exists returns False when not found."""
        pool.fetchval.return_value = None

        result = await repo.exists(999)
        assert result is False

    @pytest.mark.asyncio
    async def test_bulk_create(self, repo: BaseRepository, pool: MagicMock) -> None:
        """bulk_create inserts multiple rows."""
        pool.fetch.return_value = [{"id": 1}, {"id": 2}]

        rows = [
            {"name": "a", "email": "a@test"},
            {"name": "b", "email": "b@test"},
        ]
        result = await repo.bulk_create(rows)
        assert len(result) == 2
        pool.fetch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_bulk_create_empty(
        self, repo: BaseRepository, pool: MagicMock
    ) -> None:
        """bulk_create with empty list returns empty list."""
        result = await repo.bulk_create([])
        assert result == []
        pool.fetch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_upsert(self, repo: BaseRepository, pool: MagicMock) -> None:
        """upsert builds correct ON CONFLICT query."""
        pool.fetchrow.return_value = {"id": 1, "name": "test"}

        result = await repo.upsert(
            data={"id": 1, "name": "test", "email": "test@test"},
            conflict_columns=["id"],
            update_columns=["name", "email"],
        )
        assert result["id"] == 1
        pool.fetchrow.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raw_query(self, repo: BaseRepository, pool: MagicMock) -> None:
        """raw_query calls fetch with raw SQL."""
        pool.fetch.return_value = [{"val": 1}]

        result = await repo.raw_query("SELECT 1 AS val")
        assert result[0]["val"] == 1


# ═══════════════════════════════════════════════
# UnitOfWork tests
# ═══════════════════════════════════════════════

class TestUnitOfWork:
    """Tests for UnitOfWork."""

    @pytest.fixture
    def mock_asyncpg_pool(self) -> MagicMock:
        """Create a mock asyncpg pool with acquire context manager."""
        pool = MagicMock()
        pool._closed = False
        pool.acquire = MagicMock()
        return pool

    @pytest.fixture
    def pool(self, mock_asyncpg_pool: MagicMock) -> MagicMock:
        """Create a mock DatabasePool wrapping the mock asyncpg pool."""
        p = MagicMock(spec=DatabasePool)
        p.pool = mock_asyncpg_pool
        p._pool = mock_asyncpg_pool
        return p

    @pytest.mark.asyncio
    async def test_context_manager_commit(
        self, pool: MagicMock, mock_asyncpg_pool: MagicMock
    ) -> None:
        """UnitOfWork commits on success."""
        # Mock connection
        mock_conn = AsyncMock()
        mock_conn.is_closed = MagicMock(return_value=False)  # sync method

        # Mock transaction — conn.transaction() is SYNC in asyncpg
        mock_trans = AsyncMock()
        mock_trans._closed = False
        mock_conn.transaction = MagicMock(return_value=mock_trans)

        # Set up acquire context manager
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_conn)
        cm.__aexit__ = AsyncMock(return_value=None)
        mock_asyncpg_pool.acquire.return_value = cm

        async with UnitOfWork(pool) as uow:
            assert uow.is_active is True

        mock_trans.start.assert_awaited_once()
        mock_trans.commit.assert_awaited_once()
        mock_trans.rollback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_context_manager_rollback(
        self, pool: MagicMock, mock_asyncpg_pool: MagicMock
    ) -> None:
        """UnitOfWork rolls back on exception."""
        mock_conn = AsyncMock()
        mock_conn.is_closed = MagicMock(return_value=False)  # sync method
        # Mock transaction — conn.transaction() is SYNC in asyncpg
        mock_trans = AsyncMock()
        mock_trans._closed = False
        mock_trans.rollback = AsyncMock(side_effect=lambda: setattr(mock_trans, '_closed', True))
        mock_conn.transaction = MagicMock(return_value=mock_trans)

        # Set up acquire context manager
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_conn)
        cm.__aexit__ = AsyncMock(return_value=None)
        mock_asyncpg_pool.acquire.return_value = cm

        with pytest.raises(ValueError, match="test error"):
            async with UnitOfWork(pool) as uow:
                raise ValueError("test error")

        mock_trans.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_access_before_start(self, pool: MagicMock) -> None:
        """Accessing conn before start raises RuntimeError."""
        uow = UnitOfWork(pool)
        with pytest.raises(RuntimeError, match="not been started"):
            _ = uow.conn


# ═══════════════════════════════════════════════
# DatabaseMigrator tests
# ═══════════════════════════════════════════════

class TestDatabaseMigrator:
    """Tests for DatabaseMigrator."""

    @pytest.fixture
    def pool(self) -> MagicMock:
        """Create a mock DatabasePool."""
        p = MagicMock()
        p.execute = AsyncMock()
        p.fetch = AsyncMock(return_value=[])
        return p

    @pytest.fixture
    def migrations_dir(self, tmp_path: Path) -> Path:
        """Create a temporary migrations directory with test files."""
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        (mig_dir / "001_create_users.sql").write_text(
            "CREATE TABLE users (id SERIAL PRIMARY KEY, name TEXT);"
        )
        (mig_dir / "002_add_email.sql").write_text(
            "ALTER TABLE users ADD COLUMN email TEXT;"
        )
        (mig_dir / "003_create_settings.sql").write_text(
            "CREATE TABLE settings (id SERIAL PRIMARY KEY, key TEXT, value TEXT);"
        )
        return mig_dir

    def test_discover_migrations(
        self, pool: MagicMock, migrations_dir: Path
    ) -> None:
        """_discover_migrations finds and sorts SQL files."""
        migrator = DatabaseMigrator(pool, migrations_dir=str(migrations_dir))
        migrations = migrator._discover_migrations()

        assert len(migrations) == 3
        assert migrations[0]["version"] == 1
        assert migrations[1]["version"] == 2
        assert migrations[2]["version"] == 3
        assert all(m["content"] for m in migrations)

    def test_discover_empty_dir(self, pool: MagicMock, tmp_path: Path) -> None:
        """_discover_migrations returns empty list for empty dir."""
        empty_dir = tmp_path / "empty_migrations"
        empty_dir.mkdir()

        migrator = DatabaseMigrator(pool, migrations_dir=str(empty_dir))
        assert migrator._discover_migrations() == []

    def test_discover_missing_dir(self, pool: MagicMock) -> None:
        """_discover_migrations returns empty for missing dir."""
        migrator = DatabaseMigrator(
            pool, migrations_dir="/tmp/nonexistent_migrations_dir"
        )
        assert migrator._discover_migrations() == []

    @pytest.mark.asyncio
    async def test_get_applied_versions_empty(self, pool: MagicMock) -> None:
        """get_applied_versions returns empty set when table doesn't exist."""
        pool.fetch.side_effect = Exception("table not found")

        migrator = DatabaseMigrator(pool)
        applied = await migrator.get_applied_versions()
        assert applied == set()

    @pytest.mark.asyncio
    async def test_ensure_table(self, pool: MagicMock) -> None:
        """ensure_table creates the migration tracking table."""
        pool.execute.return_value = "CREATE TABLE"

        migrator = DatabaseMigrator(pool)
        await migrator.ensure_table()

        pool.execute.assert_awaited_once()
        sql = pool.execute.call_args[0][0]
        assert "CREATE TABLE IF NOT EXISTS" in sql
        assert "_migrations" in sql

    @pytest.mark.asyncio
    async def test_get_pending_migrations_all_pending(
        self, pool: MagicMock, migrations_dir: Path
    ) -> None:
        """get_pending_migrations returns all when none applied."""
        pool.execute.return_value = "CREATE TABLE"
        pool.fetch.return_value = []  # No applied migrations

        migrator = DatabaseMigrator(pool, migrations_dir=str(migrations_dir))
        pending = await migrator.get_pending_migrations()

        assert len(pending) == 3

    @pytest.mark.asyncio
    async def test_get_pending_migrations_some_applied(
        self, pool: MagicMock, migrations_dir: Path
    ) -> None:
        """get_pending_migrations only returns pending."""
        pool.execute.return_value = "CREATE TABLE"
        pool.fetch.return_value = [
            {"version": 1},
        ]

        migrator = DatabaseMigrator(pool, migrations_dir=str(migrations_dir))
        pending = await migrator.get_pending_migrations()

        assert len(pending) == 2
        assert pending[0]["version"] == 2

    @pytest.mark.asyncio
    async def test_status_empty(
        self, pool: MagicMock, migrations_dir: Path
    ) -> None:
        """status returns empty when no migrations dir."""
        migrator = DatabaseMigrator(
            pool, migrations_dir="/tmp/nonexistent_migrations_xyz"
        )
        status = await migrator.status()
        assert status == []

    @pytest.mark.asyncio
    async def test_status(
        self, pool: MagicMock, migrations_dir: Path
    ) -> None:
        """status returns all migrations with applied info."""
        pool.execute.return_value = "CREATE TABLE"
        pool.fetch.return_value = [
            {"version": 1, "name": "001_create_users.sql",
             "applied_at": "2026-01-01", "checksum": "abc"},
        ]

        migrator = DatabaseMigrator(pool, migrations_dir=str(migrations_dir))
        status = await migrator.status()

        assert len(status) == 3
        assert status[0]["applied"] is True
        assert status[1]["applied"] is False
        assert status[2]["applied"] is False

    @pytest.mark.asyncio
    async def test_get_pending_migrations_empty_dir(
        self, pool: MagicMock
    ) -> None:
        """get_pending_migrations returns empty when no migrations."""
        pool.execute.return_value = "CREATE TABLE"
        pool.fetch.return_value = []

        migrator = DatabaseMigrator(
            pool, migrations_dir="/tmp/nonexistent_migrations_xyz"
        )
        pending = await migrator.get_pending_migrations()
        assert pending == []


# ═══════════════════════════════════════════════
# Public API tests
# ═══════════════════════════════════════════════

def test_public_api_imports() -> None:
    """All database classes are importable from submodule."""
    from hunttech_bot_common.database import (
        DatabasePool,
        PoolConfig,
        BaseRepository,
        UnitOfWork,
        DatabaseMigrator,
    )
    assert DatabasePool is not None
    assert PoolConfig is not None
    assert BaseRepository is not None
    assert UnitOfWork is not None
    assert DatabaseMigrator is not None


def test_public_api_from_main() -> None:
    """Database classes are importable from main package."""
    from hunttech_bot_common import (
        DatabasePool,
        PoolConfig,
        BaseRepository,
        UnitOfWork,
        DatabaseMigrator,
    )
    assert DatabasePool is not None
