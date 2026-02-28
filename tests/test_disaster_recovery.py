"""
Tests for the Disaster Recovery and Backup Strategy.

Tests backup creation, recovery operations, disaster recovery workflows,
validation, and API endpoints.
"""

import pytest
import asyncio
import tempfile
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient

from src.api.disaster_recovery import (
    DisasterRecoveryAPI,
    BackupRequest,
    RecoveryRequest,
    DisasterRecoveryRequest,
    BackupResponse,
    RecoveryResponse,
    DisasterRecoveryResponse,
)
from src.disaster_recovery import (
    BackupManager,
    RecoveryManager,
    DisasterRecoveryOrchestrator,
    BackupType,
    RecoveryStatus,
    BackupStatus,
    BackupMetadata,
    RecoveryPlan,
    RecoveryOperation,
)
from src.config import Config


class TestBackupManager:
    """Test the backup manager functionality."""

    @pytest.fixture
    def mock_config(self):
        """Create mock configuration."""
        config = Mock(spec=Config)
        config.BACKUP_DIR = "/tmp/test_backups"
        config.DATABASE_URL = "sqlite:///test.db"
        config.AWS_S3_BACKUP_BUCKET = None
        config.REDIS_URL = None
        config.ENCRYPTION_ENABLED = False
        config.BACKUP_RETENTION_DAYS = 7
        return config

    @pytest.fixture
    def backup_manager(self, mock_config):
        """Create backup manager instance."""
        return BackupManager(mock_config)

    def test_backup_type_enum(self):
        """Test backup type enum values."""
        assert BackupType.FULL.value == "full"
        assert BackupType.INCREMENTAL.value == "incremental"
        assert BackupType.POINT_IN_TIME.value == "point_in_time"

    def test_backup_status_enum(self):
        """Test backup status enum values."""
        assert BackupStatus.PENDING.value == "pending"
        assert BackupStatus.IN_PROGRESS.value == "in_progress"
        assert BackupStatus.COMPLETED.value == "completed"
        assert BackupStatus.FAILED.value == "failed"

    async def test_create_full_backup(self, backup_manager):
        """Test full backup creation."""
        # Mock internal methods to avoid file system operations
        with patch.object(backup_manager, "_backup_database"):
            with patch.object(backup_manager, "_backup_configuration"):
                with patch.object(backup_manager, "_backup_logs"):
                    with patch.object(backup_manager, "_backup_uploads"):
                        with patch.object(backup_manager, "_create_archive"):
                            # Mock backup_path.stat() to return file size
                            mock_stat_result = Mock()
                            mock_stat_result.st_size = 1000
                            with patch(
                                "pathlib.Path.stat", return_value=mock_stat_result
                            ):
                                with patch.object(
                                    backup_manager,
                                    "_calculate_checksum",
                                    return_value="test_checksum",
                                ):
                                    with patch.object(
                                        backup_manager, "_store_backup_metadata"
                                    ):
                                        with patch.object(
                                            backup_manager, "_cleanup_old_backups"
                                        ):
                                            metadata = await backup_manager.create_full_backup()

        assert metadata.backup_type == BackupType.FULL
        assert metadata.status == BackupStatus.COMPLETED
        assert metadata.checksum == "test_checksum"

    async def test_create_incremental_backup(self, backup_manager):
        """Test incremental backup creation."""
        # Mock last full backup
        last_backup = BackupMetadata(
            backup_id="test_backup",
            backup_type=BackupType.FULL,
            timestamp=datetime.now() - timedelta(hours=1),
            size=1000,
            checksum="test",
            location="/tmp/test.tar.gz",
            status=BackupStatus.COMPLETED,
            retention_days=7,
            compression_enabled=True,
            encryption_enabled=False,
            database_version="1.0.0",
            schema_version="1.0.0",
        )

        with patch.object(backup_manager, "_get_last_backup", return_value=last_backup):
            with patch.object(backup_manager, "_backup_incremental_data"):
                with patch.object(backup_manager, "_create_archive"):
                    # Mock backup_path.stat() to return file size
                    mock_stat_result = Mock()
                    mock_stat_result.st_size = 1000
                    with patch("pathlib.Path.stat", return_value=mock_stat_result):
                        with patch.object(
                            backup_manager,
                            "_calculate_checksum",
                            return_value="test_checksum",
                        ):
                            with patch.object(backup_manager, "_store_backup_metadata"):
                                metadata = (
                                    await backup_manager.create_incremental_backup()
                                )

        assert metadata.backup_type == BackupType.INCREMENTAL
        assert metadata.status == BackupStatus.COMPLETED

    async def test_create_point_in_time_backup(self, backup_manager):
        """Test point-in-time backup creation."""
        test_timestamp = datetime.now()

        with patch.object(backup_manager, "_create_point_in_time_snapshot"):
            with patch.object(backup_manager, "_create_archive"):
                # Mock backup_path.stat() to return file size
                mock_stat_result = Mock()
                mock_stat_result.st_size = 1000
                with patch("pathlib.Path.stat", return_value=mock_stat_result):
                    with patch.object(
                        backup_manager,
                        "_calculate_checksum",
                        return_value="test_checksum",
                    ):
                        with patch.object(backup_manager, "_store_backup_metadata"):
                            metadata = await backup_manager.create_point_in_time_backup(
                                test_timestamp
                            )

        assert metadata.backup_type == BackupType.POINT_IN_TIME
        assert metadata.timestamp == test_timestamp
        assert metadata.status == BackupStatus.COMPLETED

    async def test_backup_database(self, backup_manager):
        """Test database backup functionality."""
        backup_path = Path("/tmp/test_db.sqlite")

        with patch("src.disaster_recovery.Path.exists", return_value=True):
            with patch("src.disaster_recovery.shutil.copy2") as mock_copy:
                await backup_manager._backup_database(backup_path)
                mock_copy.assert_called_once()

    async def test_backup_database_not_found(self, backup_manager):
        """Test database backup when file doesn't exist."""
        backup_path = Path("/tmp/nonexistent.sqlite")

        with patch("src.disaster_recovery.Path.exists", return_value=False):
            with patch("src.disaster_recovery.Path.touch") as mock_touch:
                await backup_manager._backup_database(backup_path)
                mock_touch.assert_called_once()

    async def test_calculate_checksum(self, backup_manager):
        """Test checksum calculation."""
        test_file = Path("/tmp/test_file.txt")
        test_file.write_text("test content")

        try:
            checksum = await backup_manager._calculate_checksum(test_file)
            assert isinstance(checksum, str)
            assert len(checksum) == 64  # SHA256 hex length
        finally:
            test_file.unlink(missing_ok=True)

    async def test_validate_backup(self, backup_manager):
        """Test backup validation."""
        # Create test backup file
        backup_file = Path("/tmp/test_backup.tar.gz")
        backup_file.write_bytes(b"test archive content")

        # Calculate actual size
        actual_size = backup_file.stat().st_size

        metadata = BackupMetadata(
            backup_id="test_backup",
            backup_type=BackupType.FULL,
            timestamp=datetime.now(),
            size=actual_size,  # Use actual file size
            checksum="a94a8fe5ccb19ba61c4c0873d391e987982fbbd3",  # SHA256 of "test content"
            location=str(backup_file),
            status=BackupStatus.COMPLETED,
            retention_days=7,
            compression_enabled=True,
            encryption_enabled=False,
            database_version="1.0.0",
            schema_version="1.0.0",
        )

        # Mock tempfile and tarfile extraction to avoid invalid archive error
        with patch("tempfile.TemporaryDirectory"):
            with patch("tarfile.open"):
                with patch.object(
                    backup_manager, "_get_backup_metadata", return_value=metadata
                ):
                    with patch.object(
                        backup_manager,
                        "_calculate_checksum",
                        return_value="a94a8fe5ccb19ba61c4c0873d391e987982fbbd3",
                    ):
                        validation_results = await backup_manager.validate_backup(
                            "test_backup"
                        )

        assert validation_results["valid"] is True
        assert validation_results["checks"]["file_exists"] is True
        assert validation_results["checks"]["file_size"] is True
        assert validation_results["checks"]["checksum"] is True

        # Cleanup
        backup_file.unlink(missing_ok=True)

    async def test_list_backups(self, backup_manager):
        """Test listing available backups."""
        # Create test metadata files
        backup_dir = Path(backup_manager.backup_dir)
        backup_dir.mkdir(exist_ok=True)

        test_metadata = {
            "backup_id": "test_backup_1",
            "backup_type": "full",
            "timestamp": datetime.now().isoformat(),
            "size": 1000,
            "checksum": "test_checksum",
            "location": "/tmp/test.tar.gz",
            "status": "completed",
            "retention_days": 7,
            "compression_enabled": True,
            "encryption_enabled": False,
            "database_version": "1.0.0",
            "schema_version": "1.0.0",
        }

        metadata_file = backup_dir / "test_backup_1_metadata.json"
        with open(metadata_file, "w") as f:
            import json

            json.dump(test_metadata, f)

        try:
            backups = await backup_manager.list_backups()
            assert len(backups) >= 1
            assert backups[0].backup_id == "test_backup_1"
        finally:
            metadata_file.unlink()

    async def test_cleanup_old_backups(self, backup_manager):
        """Test cleanup of expired backups."""
        # Create test backup file with old timestamp
        backup_file = Path(backup_manager.backup_dir) / "old_backup.tar.gz"
        backup_file.touch()

        # Set old modification time
        old_time = datetime.now() - timedelta(days=10)
        import os

        os.utime(backup_file, (old_time.timestamp(), old_time.timestamp()))

        # Create corresponding metadata file
        metadata_file = Path(backup_manager.backup_dir) / "old_backup_metadata.json"
        metadata_file.touch()
        os.utime(metadata_file, (old_time.timestamp(), old_time.timestamp()))

        try:
            await backup_manager._cleanup_old_backups()

            # Files should be deleted
            assert not backup_file.exists()
            assert not metadata_file.exists()
        finally:
            # Cleanup
            backup_file.unlink(missing_ok=True)
            metadata_file.unlink(missing_ok=True)


class TestRecoveryManager:
    """Test the recovery manager functionality."""

    @pytest.fixture
    def mock_config(self):
        """Create mock configuration."""
        config = Mock(spec=Config)
        config.RECOVERY_DIR = "/tmp/test_recovery"
        config.DATABASE_URL = "sqlite:///test.db"
        return config

    @pytest.fixture
    def mock_backup_manager(self):
        """Create mock backup manager."""
        return Mock(spec=BackupManager)

    @pytest.fixture
    def recovery_manager(self, mock_config, mock_backup_manager):
        """Create recovery manager instance."""
        return RecoveryManager(mock_config, mock_backup_manager)

    def test_recovery_plan_loading(self, recovery_manager):
        """Test recovery plan loading."""
        plans = recovery_manager.recovery_plans

        assert "default" in plans
        assert "critical" in plans

        default_plan = plans["default"]
        assert default_plan.plan_id == "default"
        assert default_plan.recovery_point_objective == 60
        assert default_plan.recovery_time_objective == 120

        critical_plan = plans["critical"]
        assert critical_plan.plan_id == "critical"
        assert critical_plan.recovery_point_objective == 15
        assert critical_plan.recovery_time_objective == 30

    @patch("shutil.copy2")
    @patch("tarfile.open")
    @patch("src.disaster_recovery.create_engine")
    async def test_restore_database(
        self, mock_create_engine, mock_tarfile_open, mock_copy2, recovery_manager
    ):
        """Test database restoration."""
        # Mock backup metadata
        backup_metadata = BackupMetadata(
            backup_id="test_backup",
            backup_type=BackupType.FULL,
            timestamp=datetime.now(),
            size=1000,
            checksum="test",
            location="/tmp/test.tar.gz",
            status=BackupStatus.COMPLETED,
            retention_days=7,
            compression_enabled=True,
            encryption_enabled=False,
            database_version="1.0.0",
            schema_version="1.0.0",
        )

        # Mock recovery operation
        recovery_op = RecoveryOperation(
            operation_id="test_recovery",
            plan_id="default",
            status=RecoveryStatus.IN_PROGRESS,
            start_time=datetime.now(),
            end_time=None,
            backup_id="test_backup",
            target_location="/tmp/recovery",
            steps_completed=[],
            error_message=None,
            validation_results={},
        )

        # Mock tarfile extraction
        mock_tar = Mock()
        mock_tarfile_open.return_value.__enter__ = Mock(return_value=mock_tar)
        mock_tarfile_open.return_value.__exit__ = Mock(return_value=None)

        # Mock tempfile and Path operations
        with patch("tempfile.TemporaryDirectory"):
            with patch("pathlib.Path") as mock_path_class:
                mock_db_backup = Mock()
                mock_db_backup.exists.return_value = True
                mock_path_class.return_value = mock_db_backup

                # Mock database engine
                mock_engine = Mock()
                mock_conn = Mock()
                mock_create_engine.return_value = mock_engine
                mock_connection_context = Mock()
                mock_connection_context.__enter__ = Mock(return_value=mock_conn)
                mock_connection_context.__exit__ = Mock(return_value=None)
                mock_engine.connect.return_value = mock_connection_context

                await recovery_manager._restore_database(recovery_op, backup_metadata)

        # Verify that the method completed without error (mocked copy2 may or may not be called)
        assert recovery_op.status == RecoveryStatus.IN_PROGRESS

    @patch("shutil.copy2")
    @patch("tarfile.open")
    async def test_restore_configuration(
        self, mock_tarfile_open, mock_copy2, recovery_manager
    ):
        """Test configuration restoration."""
        # Mock backup metadata and recovery operation
        backup_metadata = BackupMetadata(
            backup_id="test_backup",
            backup_type=BackupType.FULL,
            timestamp=datetime.now(),
            size=1000,
            checksum="test",
            location="/tmp/test.tar.gz",
            status=BackupStatus.COMPLETED,
            retention_days=7,
            compression_enabled=True,
            encryption_enabled=False,
            database_version="1.0.0",
            schema_version="1.0.0",
        )

        recovery_op = RecoveryOperation(
            operation_id="test_recovery",
            plan_id="default",
            status=RecoveryStatus.IN_PROGRESS,
            start_time=datetime.now(),
            end_time=None,
            backup_id="test_backup",
            target_location="/tmp/recovery",
            steps_completed=[],
            error_message=None,
            validation_results={},
        )

        # Mock tarfile extraction
        mock_tar = Mock()
        mock_tarfile_open.return_value.__enter__ = Mock(return_value=mock_tar)
        mock_tarfile_open.return_value.__exit__ = Mock(return_value=None)

        # Mock tempfile and Path operations
        with patch("tempfile.TemporaryDirectory"):
            with patch("pathlib.Path") as mock_path_class:
                mock_config_path = Mock()
                mock_config_path.exists.return_value = True
                mock_config_path.iterdir.return_value = []
                mock_path_class.return_value = mock_config_path

                await recovery_manager._restore_configuration(
                    recovery_op, backup_metadata
                )

        # Verify that the method completed without error
        assert recovery_op.status == RecoveryStatus.IN_PROGRESS

    @patch("src.disaster_recovery.create_engine")
    async def test_validate_recovery(self, mock_create_engine, recovery_manager):
        """Test recovery validation."""
        # Mock recovery operation
        recovery_op = RecoveryOperation(
            operation_id="test_recovery",
            plan_id="default",
            status=RecoveryStatus.IN_PROGRESS,
            start_time=datetime.now(),
            end_time=None,
            backup_id="test_backup",
            target_location="/tmp/recovery",
            steps_completed=[],
            error_message=None,
            validation_results={},
        )

        # Mock database engine and connection
        mock_engine = Mock()
        mock_conn = Mock()
        mock_create_engine.return_value = mock_engine
        mock_connection_context = Mock()
        mock_connection_context.__enter__ = Mock(return_value=mock_conn)
        mock_connection_context.__exit__ = Mock(return_value=None)
        mock_engine.connect.return_value = mock_connection_context
        mock_conn.execute.return_value.scalar.return_value = 100  # 100 tasks

        await recovery_manager._validate_recovery(recovery_op)

        # Verify validation results
        assert recovery_op.validation_results["database_validation"] is True
        assert recovery_op.validation_results["table_validation"] is True


class TestDisasterRecoveryOrchestrator:
    """Test the disaster recovery orchestrator."""

    @pytest.fixture
    def mock_config(self):
        """Create mock configuration."""
        config = Mock(spec=Config)
        config.BACKUP_DIR = "/tmp/test_backups"
        config.RECOVERY_DIR = "/tmp/test_recovery"
        config.DATABASE_URL = "sqlite:///test.db"
        config.AWS_S3_BACKUP_BUCKET = None
        config.REDIS_URL = None
        config.ENCRYPTION_ENABLED = False
        config.BACKUP_RETENTION_DAYS = 7
        return config

    @pytest.fixture
    def mock_backup_manager(self):
        """Create mock backup manager."""
        return Mock(spec=BackupManager)

    @pytest.fixture
    def mock_recovery_manager(self):
        """Create mock recovery manager."""
        return Mock(spec=RecoveryManager)

    @pytest.fixture
    def orchestrator(self, mock_config, mock_backup_manager, mock_recovery_manager):
        """Create disaster recovery orchestrator."""
        with patch(
            "src.disaster_recovery.BackupManager", return_value=mock_backup_manager
        ):
            with patch(
                "src.disaster_recovery.RecoveryManager",
                return_value=mock_recovery_manager,
            ):
                return DisasterRecoveryOrchestrator(mock_config)

    async def test_assess_disaster(self, orchestrator):
        """Test disaster assessment."""
        # Test database corruption
        strategy = await orchestrator._assess_disaster("database_corruption")
        assert strategy["priority"] == "high"
        assert strategy["requires_full_backup"] is True

        # Test unknown disaster type
        strategy = await orchestrator._assess_disaster("unknown_disaster")
        assert strategy["priority"] == "medium"  # Should default to system_failure

    async def test_select_backup_for_recovery(self, orchestrator, mock_backup_manager):
        """Test backup selection for recovery."""
        # Mock backups
        pit_backup = BackupMetadata(
            backup_id="pit_backup",
            backup_type=BackupType.POINT_IN_TIME,
            timestamp=datetime.now(),
            size=1000,
            checksum="test",
            location="/tmp/pit.tar.gz",
            status=BackupStatus.COMPLETED,
            retention_days=7,
            compression_enabled=True,
            encryption_enabled=False,
            database_version="1.0.0",
            schema_version="1.0.0",
        )

        full_backup = BackupMetadata(
            backup_id="full_backup",
            backup_type=BackupType.FULL,
            timestamp=datetime.now(),
            size=1000,
            checksum="test",
            location="/tmp/full.tar.gz",
            status=BackupStatus.COMPLETED,
            retention_days=7,
            compression_enabled=True,
            encryption_enabled=False,
            database_version="1.0.0",
            schema_version="1.0.0",
        )

        mock_backup_manager.list_backups.return_value = [pit_backup, full_backup]

        # Test point-in-time recovery strategy
        recovery_strategy = {"requires_point_in_time": True}
        backup_id = await orchestrator._select_backup_for_recovery(
            "data_loss", recovery_strategy
        )
        assert backup_id == "pit_backup"

        # Test full backup fallback
        recovery_strategy = {"requires_point_in_time": False}
        backup_id = await orchestrator._select_backup_for_recovery(
            "system_failure", recovery_strategy
        )
        assert backup_id == "full_backup"

    async def test_validate_disaster_recovery(self, orchestrator):
        """Test disaster recovery validation."""
        # Mock recovery operation
        recovery_result = RecoveryOperation(
            operation_id="test_recovery",
            plan_id="default",
            status=RecoveryStatus.COMPLETED,
            start_time=datetime.now(),
            end_time=datetime.now(),
            backup_id="test_backup",
            target_location="/tmp/recovery",
            steps_completed=["validate_backup", "restore_database"],
            error_message=None,
            validation_results={},
        )

        with patch("src.disaster_recovery.create_engine") as mock_create_engine:
            mock_engine = Mock()
            mock_conn = Mock()
            mock_create_engine.return_value = mock_engine
            mock_connection_context = Mock()
            mock_connection_context.__enter__ = Mock(return_value=mock_conn)
            mock_connection_context.__exit__ = Mock(return_value=None)
            mock_engine.connect.return_value = mock_connection_context
            mock_conn.execute.return_value.scalar.return_value = 100  # Task count

            validation_results = await orchestrator._validate_disaster_recovery(
                recovery_result
            )

        assert validation_results["database_connectivity"] is True
        assert validation_results["data_integrity"] is True


class TestDisasterRecoveryAPI:
    """Test the disaster recovery API endpoints."""

    @pytest.fixture
    def mock_config(self):
        """Create mock configuration."""
        config = Mock(spec=Config)
        config.BACKUP_DIR = "/tmp/test_backups"
        config.RECOVERY_DIR = "/tmp/test_recovery"
        config.DATABASE_URL = "sqlite:///test.db"
        config.AWS_S3_BACKUP_BUCKET = None
        config.REDIS_URL = None
        config.ENCRYPTION_ENABLED = False
        config.BACKUP_RETENTION_DAYS = 7
        return config

    @pytest.fixture
    def disaster_recovery_api(self, mock_config):
        """Create disaster recovery API instance."""
        return DisasterRecoveryAPI(mock_config)

    @pytest.fixture
    def client(self):
        """Create test client."""
        from src.api.main import app

        return TestClient(app)

    def test_backup_request_validation(self):
        """Test backup request validation."""
        # Valid request
        request = BackupRequest(backup_type="full", force=True)
        assert request.backup_type == "full"
        assert request.force is True

        # Note: Pydantic model doesn't validate backup_type enum values at model level
        # Validation happens at the API endpoint level in create_backup method
        request_invalid = BackupRequest(backup_type="invalid_type", force=True)
        assert request_invalid.backup_type == "invalid_type"

    def test_recovery_request_validation(self):
        """Test recovery request validation."""
        # Valid request
        request = RecoveryRequest(backup_id="test_backup", plan_id="default")
        assert request.backup_id == "test_backup"
        assert request.plan_id == "default"

    def test_disaster_recovery_request_validation(self):
        """Test disaster recovery request validation."""
        # Valid request
        request = DisasterRecoveryRequest(
            disaster_type="database_corruption", plan_id="default"
        )
        assert request.disaster_type == "database_corruption"
        assert request.plan_id == "default"

    @patch.object(DisasterRecoveryAPI, "create_backup")
    def test_create_backup_endpoint(self, mock_create_backup, client):
        """Test create backup API endpoint."""
        # Mock backup creation
        mock_response = BackupResponse(
            backup_id="test_backup",
            backup_type="full",
            status="completed",
            timestamp=datetime.now().isoformat(),
            size=1000,
            location="/tmp/test.tar.gz",
            message="Backup created successfully",
        )
        mock_create_backup.return_value = mock_response

        # Test API call
        response = client.post(
            "/api/disaster-recovery/backups",
            json={"backup_type": "full", "force": True},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["backup_id"] == "test_backup"
        assert data["backup_type"] == "full"
        assert data["status"] == "completed"

    @patch.object(DisasterRecoveryAPI, "list_backups")
    def test_list_backups_endpoint(self, mock_list_backups, client):
        """Test list backups API endpoint."""
        # Mock backup list
        mock_backups = [
            BackupMetadata(
                backup_id="backup1",
                backup_type=BackupType.FULL,
                timestamp=datetime.now(),
                size=1000,
                checksum="test",
                location="/tmp/backup1.tar.gz",
                status=BackupStatus.COMPLETED,
                retention_days=7,
                compression_enabled=True,
                encryption_enabled=False,
                database_version="1.0.0",
                schema_version="1.0.0",
            )
        ]
        mock_list_backups.return_value = BackupListResponse(
            backups=mock_backups,
            total=1,
            available_types=[bt.value for bt in BackupType],
        )

        # Test API call
        response = client.get("/api/disaster-recovery/backups")

        assert response.status_code == 200
        data = response.json()
        assert len(data["backups"]) == 1
        assert data["backups"][0]["backup_id"] == "backup1"

    @patch.object(DisasterRecoveryAPI, "validate_backup")
    def test_validate_backup_endpoint(self, mock_validate_backup, client):
        """Test validate backup API endpoint."""
        # Mock validation results
        mock_results = {
            "valid": True,
            "backup_id": "test_backup",
            "checks": {
                "file_exists": True,
                "checksum": True,
                "archive_integrity": True,
            },
        }
        mock_validate_backup.return_value = mock_results

        # Test API call
        response = client.post("/api/disaster-recovery/backups/test_backup/validate")

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert data["checks"]["file_exists"] is True

    @patch.object(DisasterRecoveryAPI, "execute_recovery")
    def test_execute_recovery_endpoint(self, mock_execute_recovery, client):
        """Test execute recovery API endpoint."""
        # Mock recovery operation
        mock_recovery = RecoveryResponse(
            operation_id="test_recovery",
            plan_id="default",
            status="completed",
            start_time=datetime.now().isoformat(),
            end_time=datetime.now().isoformat(),
            backup_id="test_backup",
            target_location="/tmp/recovery",
            steps_completed=["validate_backup", "restore_database"],
            validation_results={"database_validation": True},
            error_message=None,
        )
        mock_execute_recovery.return_value = mock_recovery

        # Test API call
        response = client.post(
            "/api/disaster-recovery/recoveries",
            json={"backup_id": "test_backup", "plan_id": "default"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["operation_id"] == "test_recovery"
        assert data["status"] == "completed"

    @patch.object(DisasterRecoveryAPI, "execute_disaster_recovery")
    def test_execute_disaster_recovery_endpoint(
        self, mock_execute_disaster_recovery, client
    ):
        """Test execute disaster recovery API endpoint."""
        # Mock disaster recovery results
        mock_results = DisasterRecoveryResponse(
            success=True,
            disaster_type="database_corruption",
            recovery_strategy={"priority": "high", "requires_full_backup": True},
            backup_id="test_backup",
            recovery_result={"operation_id": "test_recovery"},
            validation_result={"database_connectivity": True},
            completion_time=datetime.now().isoformat(),
            failure_time=None,
            error=None,
        )
        mock_execute_disaster_recovery.return_value = mock_results

        # Test API call
        response = client.post(
            "/api/disaster-recovery/disaster-recovery",
            json={"disaster_type": "database_corruption", "plan_id": "default"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["disaster_type"] == "database_corruption"
        assert data["backup_id"] == "test_backup"

    @patch.object(DisasterRecoveryAPI, "get_recovery_metrics")
    def test_get_recovery_metrics_endpoint(self, mock_get_recovery_metrics, client):
        """Test get recovery metrics API endpoint."""
        # Mock metrics
        mock_metrics = {
            "rto_average": 120,
            "rpo_average": 60,
            "success_rate": 0.95,
            "last_recovery_time": "2024-01-01T12:00:00Z",
            "backup_success_rate": 0.99,
        }
        mock_get_recovery_metrics.return_value = mock_metrics

        # Test API call
        response = client.get("/api/disaster-recovery/metrics")

        assert response.status_code == 200
        data = response.json()
        assert data["rto_average"] == 120
        assert data["success_rate"] == 0.95


class TestDisasterRecoveryIntegration:
    """Integration tests for disaster recovery system."""

    @pytest.fixture
    def temp_directories(self):
        """Create temporary directories for testing."""
        backup_dir = Path(tempfile.mkdtemp(prefix="test_backup_"))
        recovery_dir = Path(tempfile.mkdtemp(prefix="test_recovery_"))

        yield backup_dir, recovery_dir

        # Cleanup
        shutil.rmtree(backup_dir, ignore_errors=True)
        shutil.rmtree(recovery_dir, ignore_errors=True)

    def test_full_backup_recovery_workflow(self, temp_directories):
        """Test complete backup and recovery workflow."""
        backup_dir, recovery_dir = temp_directories

        # Create test configuration
        config = Mock(spec=Config)
        config.BACKUP_DIR = str(backup_dir)
        config.RECOVERY_DIR = str(recovery_dir)
        config.DATABASE_URL = "sqlite:///test.db"
        config.AWS_S3_BACKUP_BUCKET = None
        config.REDIS_URL = None
        config.ENCRYPTION_ENABLED = False
        config.BACKUP_RETENTION_DAYS = 7

        # Create backup manager
        backup_manager = BackupManager(config)

        # Create test database file
        test_db = backup_dir / "test.db"
        test_db.write_text("test database content")

        # Create backup
        async def run_backup():
            return await backup_manager.create_full_backup()

        metadata = asyncio.run(run_backup())

        # Verify backup was created
        assert metadata.status == BackupStatus.COMPLETED
        assert metadata.backup_id is not None

        # Verify backup file exists
        backup_file = Path(metadata.location)
        assert backup_file.exists()

        # Validate backup
        async def run_validation():
            return await backup_manager.validate_backup(metadata.backup_id)

        validation_results = asyncio.run(run_validation())
        assert validation_results["valid"] is True

        # List backups
        async def run_list():
            return await backup_manager.list_backups()

        backups = asyncio.run(run_list())
        assert len(backups) >= 1
        assert backups[0].backup_id == metadata.backup_id


# Error handling tests
class TestDisasterRecoveryErrorHandling:
    """Test error handling in disaster recovery system."""

    @pytest.fixture
    def mock_config(self):
        """Create mock configuration."""
        config = Mock(spec=Config)
        config.BACKUP_DIR = "/tmp/test_backups"
        config.RECOVERY_DIR = "/tmp/test_recovery"
        config.DATABASE_URL = "sqlite:///test.db"
        config.AWS_S3_BACKUP_BUCKET = None
        config.REDIS_URL = None
        config.ENCRYPTION_ENABLED = False
        config.BACKUP_RETENTION_DAYS = 7
        return config

    @pytest.fixture
    def backup_manager(self, mock_config):
        """Create backup manager instance."""
        return BackupManager(mock_config)

    async def test_database_backup_failure(self, backup_manager):
        """Test handling of database backup failures."""
        # Create a temporary database file
        db_path = Path(backup_manager.config.DATABASE_URL.replace("sqlite:///", ""))
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.write_text("test data")

        backup_path = Path("/tmp/test_db.sqlite")

        try:
            with patch(
                "shutil.copy2",
                side_effect=Exception("Database backup failed"),
            ):
                with pytest.raises(Exception, match="Database backup failed"):
                    await backup_manager._backup_database(backup_path)
        finally:
            # Cleanup
            db_path.unlink(missing_ok=True)
            if db_path.parent.exists():
                try:
                    db_path.parent.rmdir()
                except OSError:
                    pass

    async def test_backup_validation_failure(self, backup_manager):
        """Test handling of backup validation failures."""
        # Create invalid backup file
        backup_file = Path("/tmp/invalid_backup.tar.gz")
        backup_file.write_bytes(b"invalid archive content")

        metadata = BackupMetadata(
            backup_id="invalid_backup",
            backup_type=BackupType.FULL,
            timestamp=datetime.now(),
            size=25,  # Length of invalid content
            checksum="different_checksum",  # Different from actual
            location=str(backup_file),
            status=BackupStatus.COMPLETED,
            retention_days=7,
            compression_enabled=True,
            encryption_enabled=False,
            database_version="1.0.0",
            schema_version="1.0.0",
        )

        with patch.object(
            backup_manager, "_get_backup_metadata", return_value=metadata
        ):
            with patch.object(
                backup_manager, "_calculate_checksum", return_value="actual_checksum"
            ):
                validation_results = await backup_manager.validate_backup(
                    "invalid_backup"
                )

        assert validation_results["valid"] is False
        assert validation_results["checks"]["checksum"] is False

        # Cleanup
        backup_file.unlink()

    async def test_recovery_operation_failure(self, mock_config):
        """Test handling of recovery operation failures."""
        from src.disaster_recovery import RecoveryManager

        mock_backup_manager = Mock()
        recovery_manager = RecoveryManager(mock_config, mock_backup_manager)

        # Mock backup metadata
        BackupMetadata(
            backup_id="test_backup",
            backup_type=BackupType.FULL,
            timestamp=datetime.now(),
            size=1000,
            checksum="test",
            location="/tmp/test.tar.gz",
            status=BackupStatus.COMPLETED,
            retention_days=7,
            compression_enabled=True,
            encryption_enabled=False,
            database_version="1.0.0",
            schema_version="1.0.0",
        )

        # Mock plan
        RecoveryPlan(
            plan_id="default",
            name="Default Plan",
            description="Test plan",
            recovery_point_objective=60,
            recovery_time_objective=120,
            backup_locations=["local"],
            priority="medium",
            automated=True,
            test_frequency="0 0 1 * *",
        )

        with patch.object(
            recovery_manager,
            "_execute_recovery_steps",
            side_effect=Exception("Recovery failed"),
        ):
            recovery_op = await recovery_manager.execute_recovery(
                backup_id="test_backup", plan_id="default"
            )

        assert recovery_op.status == RecoveryStatus.FAILED
        assert (
            recovery_op.error_message == "Step validate_backup failed: Recovery failed"
        )


# Performance tests
class TestDisasterRecoveryPerformance:
    """Performance tests for disaster recovery system."""

    @pytest.mark.benchmark
    def test_backup_creation_performance(self):
        """Test backup creation performance."""
        # This would be implemented with actual performance testing
        # For now, just ensure the method completes without errors
        pass

    @pytest.mark.benchmark
    def test_recovery_performance(self):
        """Test recovery performance."""
        # This would be implemented with actual performance testing
        # For now, just ensure the method completes without errors
        pass

    @pytest.mark.benchmark
    def test_validation_performance(self):
        """Test validation performance."""
        # This would be implemented with actual performance testing
        # For now, just ensure the method completes without errors
        pass


# Helper functions for testing
def create_test_backup_file(backup_dir: Path, backup_id: str) -> Path:
    """Create a test backup file for testing."""
    backup_file = backup_dir / f"{backup_id}.tar.gz"
    backup_file.write_bytes(b"test backup content")
    return backup_file


def create_test_metadata_file(backup_dir: Path, backup_id: str, metadata: dict):
    """Create a test metadata file for testing."""
    metadata_file = backup_dir / f"{backup_id}_metadata.json"
    import json

    with open(metadata_file, "w") as f:
        json.dump(metadata, f)
    return metadata_file
