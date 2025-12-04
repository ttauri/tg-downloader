import os
from datetime import datetime
from typing import Optional
from collections import defaultdict

from sqlalchemy.orm import Session
from sqlalchemy import and_

from webapp.models import Media, Channel
from webapp.database import SessionLocal
from webapp.services.task_manager import Task, TaskStatus, CancelledError
from webapp.services.storage_service import (
    compute_file_hash,
    get_channel_folder_path,
    get_folder_stats,
    move_to_orphaned,
)
from webapp.logging_conf import logger


def get_downloaded_media_by_channel(db: Session, channel_id: str):
    """Get all media marked as downloaded for a channel."""
    return db.query(Media).filter(
        and_(Media.tg_channel_id == channel_id, Media.is_downloaded == True)
    ).all()


def find_duplicates_by_hash(db: Session, channel_id: str):
    """Find media records with the same file_hash in a channel."""
    media_list = db.query(Media).filter(
        and_(
            Media.tg_channel_id == channel_id,
            Media.is_downloaded == True,
            Media.file_hash != None
        )
    ).all()

    hash_groups = defaultdict(list)
    for m in media_list:
        if m.file_hash:
            hash_groups[m.file_hash].append(m)

    return {h: items for h, items in hash_groups.items() if len(items) > 1}


async def sync_channel_storage(channel_id: str, channel_name: str, task: Optional[Task] = None):
    """
    Sync database with actual files on disk.

    1. Verify each downloaded media record has a matching file
    2. Compute file hashes for deduplication
    3. Find orphan files (on disk but not in DB)
    4. Handle duplicates (keep largest, mark others)
    """
    db = SessionLocal()
    try:
        folder_path = get_channel_folder_path(channel_name)

        if not os.path.exists(folder_path):
            # Still update last_synced even if no folder
            logger.info(f"No folder exists for channel_id={channel_id}, updating last_synced anyway")
            channel = db.query(Channel).filter(Channel.channel_id == str(channel_id)).first()
            logger.info(f"Channel found: {channel is not None}")
            if channel:
                channel.last_synced = datetime.now()
                db.commit()
                logger.info(f"Updated last_synced to {channel.last_synced}")
            if task:
                await task.complete("No folder exists yet")
            return {"status": "no_folder"}

        if task:
            await task.update(status=TaskStatus.RUNNING, message="Scanning files...")

        # Get all files on disk
        disk_files = {}
        for entry in os.scandir(folder_path):
            if entry.is_file() and not entry.name.startswith('.'):
                disk_files[entry.name] = {
                    'path': entry.path,
                    'size': entry.stat().st_size,
                }

        # Get all downloaded media from DB
        downloaded_media = get_downloaded_media_by_channel(db, channel_id)
        total = len(downloaded_media)

        if task:
            await task.update(current=0, total=total, message=f"Verifying {total} records...")

        verified = 0
        missing = 0
        hashed = 0

        for i, media in enumerate(downloaded_media, 1):
            if task and task.is_cancelled:
                await task.set_cancelled(f"Stopped after {i-1}/{total}")
                return {"status": "cancelled"}

            filename = media.filename
            if filename in disk_files:
                file_info = disk_files[filename]
                media.disk_verified = True
                media.disk_size = file_info['size']

                # Compute hash if not already done
                if not media.file_hash:
                    file_hash = compute_file_hash(file_info['path'])
                    if file_hash:
                        media.file_hash = file_hash
                        hashed += 1

                # Use disk_size as quality score (larger = better)
                media.quality_score = file_info['size']

                # Remove from disk_files to track orphans
                del disk_files[filename]
                verified += 1
            else:
                # File missing from disk
                media.disk_verified = False
                media.is_downloaded = False
                media.filename = ""
                missing += 1

            if task and i % 10 == 0:
                await task.update(current=i, total=total,
                                  message=f"Verified {i}/{total} ({verified} ok, {missing} missing)")

        db.commit()

        # Handle orphan files
        orphans_moved = 0
        orphan_files = list(disk_files.keys())
        if orphan_files:
            if task:
                await task.update(message=f"Moving {len(orphan_files)} orphan files...")

            for filename in orphan_files:
                file_path = disk_files[filename]['path']
                new_path = move_to_orphaned(file_path, channel_name)
                if new_path:
                    orphans_moved += 1
                    logger.info(f"Moved orphan: {filename} -> {new_path}")

        # Handle duplicates
        if task:
            await task.update(message="Checking for duplicates...")

        duplicates = find_duplicates_by_hash(db, channel_id)
        duplicates_deleted = 0

        for file_hash, media_list in duplicates.items():
            # Sort by quality_score (disk_size) descending - keep largest
            media_list.sort(key=lambda m: m.quality_score or 0, reverse=True)
            best = media_list[0]

            for duplicate in media_list[1:]:
                if duplicate.id != best.id:
                    duplicate.duplicate_of_id = best.id
                    # Delete the duplicate file from disk
                    if duplicate.filename:
                        dup_path = os.path.join(folder_path, duplicate.filename)
                        if os.path.exists(dup_path):
                            os.remove(dup_path)
                            logger.info(f"Deleted duplicate file: {duplicate.filename} (keeping {best.filename})")
                        duplicate.is_downloaded = False
                        duplicate.filename = ""
                    duplicates_deleted += 1

        # Update last_synced timestamp on channel
        channel = db.query(Channel).filter(Channel.channel_id == str(channel_id)).first()
        logger.info(f"Updating last_synced for channel_id={channel_id}, found={channel is not None}")
        if channel:
            channel.last_synced = datetime.now()
            logger.info(f"Set last_synced to {channel.last_synced}")

        db.commit()
        logger.info("Committed last_synced update")

        result = {
            "status": "completed",
            "verified": verified,
            "missing": missing,
            "hashed": hashed,
            "orphans_moved": orphans_moved,
            "duplicates_deleted": duplicates_deleted,
        }

        if task:
            msg = f"Sync complete: {verified} verified, {missing} missing, {orphans_moved} orphans moved, {duplicates_deleted} duplicates deleted"
            await task.complete(msg)

        return result

    except CancelledError:
        logger.info("Sync cancelled by user")
        return {"status": "cancelled"}
    except Exception as e:
        logger.error(f"Sync failed: {e}")
        if task:
            await task.fail(str(e))
        raise
    finally:
        db.close()


def quick_sync_check(channel_id: str, channel_name: str) -> dict:
    """
    Quick sync check comparing DB downloaded count vs disk file count.
    Returns dict with mismatch info. Does NOT modify anything.
    """
    db = SessionLocal()
    try:
        folder_path = get_channel_folder_path(channel_name)
        folder_stats = get_folder_stats(folder_path)

        downloaded_count = db.query(Media).filter(
            and_(Media.tg_channel_id == channel_id, Media.is_downloaded == True)
        ).count()

        disk_count = folder_stats['file_count'] if folder_stats['exists'] else 0

        return {
            "channel_id": channel_id,
            "channel_name": channel_name,
            "db_downloaded": downloaded_count,
            "disk_files": disk_count,
            "mismatch": downloaded_count != disk_count,
            "folder_exists": folder_stats['exists'],
        }
    finally:
        db.close()


def startup_sync_check() -> list:
    """
    Run quick sync check for all subscribed channels on startup.
    Returns list of channels with mismatches.
    """
    db = SessionLocal()
    try:
        subscribed = db.query(Channel).filter(Channel.subscribed == True).all()
        results = []

        for channel in subscribed:
            check = quick_sync_check(channel.channel_id, channel.channel_name)
            if check['mismatch']:
                logger.warning(
                    f"Sync mismatch for {channel.channel_name}: "
                    f"DB={check['db_downloaded']}, Disk={check['disk_files']}"
                )
            results.append(check)

        mismatches = [r for r in results if r['mismatch']]
        if mismatches:
            logger.warning(f"Found {len(mismatches)} channels with sync mismatches")
        else:
            logger.info(f"Startup sync check: {len(results)} channels OK")

        return results
    finally:
        db.close()
