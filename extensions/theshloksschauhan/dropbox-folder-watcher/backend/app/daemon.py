import logging
import time
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.services.dropbox_client import DropboxClient
from app.services.superdocs_client import SuperDocsClient
from app.services.worker import WorkerLoop
from app.services.watcher import WatcherService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_daemon():
    """Runs the watcher and worker loops in a single process for simplicity."""
    logger.info("Starting daemon...")
    dropbox = DropboxClient()
    superdocs = SuperDocsClient()
    watcher = WatcherService(dropbox)
    worker = WorkerLoop(dropbox, superdocs, worker_id="daemon-1")

    db: Session = SessionLocal()
    try:
        while True:
            # 1. Watcher: Poll Dropbox for new files
            try:
                watcher.scan_all_folders(db)
            except Exception as e:
                logger.error("Watcher error: %s", e, exc_info=True)

            # 2. Worker: Process queued jobs (prepare for review)
            while True:
                try:
                    job = worker.process_next_queued(db)
                    if not job:
                        break
                except Exception as e:
                    logger.error("Worker error: %s", e, exc_info=True)
                    time.sleep(5)

            # 3. Worker: Complete human-approved jobs
            while True:
                try:
                    job = worker.process_next_approved(db)
                    if not job:
                        break
                except Exception as e:
                    logger.error("Approved worker error: %s", e, exc_info=True)
                    time.sleep(5)

            # Sleep before next polling cycle
            time.sleep(10)
    finally:
        db.close()

if __name__ == "__main__":
    run_daemon()
