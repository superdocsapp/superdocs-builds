"""Watcher service — polls Dropbox for changes and creates jobs.

This is the entry point that detects new/modified files and feeds them
into the processing pipeline. It runs as a background loop, scanning
configured folders on an interval.

For each file detected:
1. Check if it's our own output (anti-loop) -> skip
2. Check stability (content-hash debounce) -> wait
3. Check for duplicate job (idempotent by client_id + source_rev) -> skip
4. Create a new job in DISCOVERED state
5. Transition to STABILIZING, then QUEUED if stable
"""
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.client import Client
from app.models.folder_config import FolderConfig
from app.models.job import Job, JobStatus
from app.services.dropbox_client import DropboxClientProtocol, FileMetadata
from app.services.stability import check_stability, record_observation
from app.services.antiloop import is_own_output
from app.services.state_machine import transition
from app.services.budget import budget_allows_processing
from app.services.system_state import get_global_preview_mode
from app.services.isolation import path_is_under

logger = logging.getLogger(__name__)


class WatcherService:
    """Polls Dropbox folders and creates jobs for new/modified files."""

    def __init__(self, dropbox: DropboxClientProtocol):
        self.dropbox = dropbox

    def scan_folder(self, db: Session, folder_config: FolderConfig) -> list[Job]:
        """Scan a single folder and create jobs for new/modified files.

        Returns list of jobs created or updated.
        """
        if not folder_config.enabled:
            logger.debug("Folder %s is disabled — skipping", folder_config.dropbox_folder_path)
            return []

        logger.info("Scanning folder: %s", folder_config.dropbox_folder_path)

        # List files in the folder
        result = self.dropbox.list_folder(folder_config.dropbox_folder_path)
        all_entries = list(result.entries)

        # Paginate if needed
        while result.has_more:
            result = self.dropbox.list_folder_continue(result.cursor)
            all_entries.extend(result.entries)

        # Filter by allowed extensions
        if folder_config.allowed_extensions:
            allowed = [ext.lower().lstrip('.') for ext in folder_config.allowed_extensions]
            all_entries = [
                e for e in all_entries
                if any(e.name.lower().endswith(f'.{ext}') for ext in allowed)
            ]

        jobs_created = []

        for entry in all_entries:
            job = self._process_entry(db, folder_config, entry)
            if job is not None:
                jobs_created.append(job)

        if jobs_created:
            db.commit()
            logger.info("Folder %s: created/updated %d job(s)",
                       folder_config.dropbox_folder_path, len(jobs_created))

        return jobs_created

    def _process_entry(
        self, db: Session, folder_config: FolderConfig, entry: FileMetadata,
    ) -> Optional[Job]:
        """Process a single file entry from a folder scan.

        Returns a Job if one was created/updated, None if skipped.
        """
        path = entry.path

        if not path_is_under(path, folder_config.dropbox_folder_path):
            logger.debug("Skipping path outside nominated folder: %s", path)
            return None

        # 1. Anti-loop check — is this our own output?
        if is_own_output(db, path, entry.content_hash):
            logger.debug("Skipping own output: %s", path)
            return None

        # 2. Duplicate check — do we already have a job for this rev?
        existing = (
            db.query(Job)
            .filter(
                Job.folder_config_id == folder_config.id,
                Job.source_rev == entry.rev,
            )
            .first()
        )
        if existing is not None:
            logger.debug("Skipping duplicate rev %s for %s (job %s)",
                        entry.rev, path, existing.id)
            return None

        # 3. Stability check
        stability = check_stability(
            db, path, entry,
            debounce_seconds=folder_config.debounce_seconds,
        )

        if not stability.is_stable:
            logger.info("File not yet stable: %s (%s)", path, stability.reason)
            return None

        if not budget_allows_processing(db, folder_config):
            logger.warning(
                "Hourly operation budget exhausted for folder %s — skipping %s",
                folder_config.dropbox_folder_path, path,
            )
            return None

        # 4. File is stable — create a job
        preview = folder_config.preview_mode or get_global_preview_mode()
        job = Job(
            client_id=folder_config.client_id,
            folder_config_id=folder_config.id,
            source_path=path,
            source_rev=entry.rev,
            source_content_hash=entry.content_hash,
            status=JobStatus.DISCOVERED,
            preview=preview,
        )
        db.add(job)
        db.flush()

        # 5. Transition through the initial states
        transition(db, job, JobStatus.STABILIZING, actor="watcher",
                  detail=f"File stable: {stability.reason}")
        transition(db, job, JobStatus.QUEUED, actor="watcher",
                  detail="Queued for processing")

        logger.info("Created job %s for %s (rev=%s)", job.id, path, entry.rev)
        return job

    def scan_all_folders(self, db: Session) -> list[Job]:
        """Scan all enabled folder configs and create jobs."""
        configs = db.query(FolderConfig).filter(FolderConfig.enabled == True).all()

        all_jobs = []
        for config in configs:
            try:
                jobs = self.scan_folder(db, config)
                all_jobs.extend(jobs)
            except Exception as e:
                logger.error("Error scanning folder %s: %s",
                           config.dropbox_folder_path, e, exc_info=True)

        return all_jobs
