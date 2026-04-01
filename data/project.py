# data/project.py
# HBCE — Hybrid Controls Editor
# .hbce Project File — Full Implementation V0.1.7-alpha
#
# A .hbce file is a ZIP archive containing:
#   manifest.json       — metadata (version, created, app version)
#   devices.json        — list of device configs
#   programs/           — one <name>.json per FBD program
#   schedules/          — one <name>.json per schedule
#   backups/            — one <name>.json per backup entry (metadata only)
#   theme.json          — saved QSS color profile (optional)
#
# Usage:
#   ProjectFile.save(project, path)  → writes .hbce file
#   ProjectFile.load(path)           → returns Project instance
#   ProjectFile.export_zip(project, path)   → same as save
#   ProjectFile.import_zip(path)            → same as load

from __future__ import annotations

import json
import os
import zipfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from data.models import (
    AlarmPriority, BackupEntry, Device, Program, Project,
    ProtocolKind, Schedule, ScheduleBlock,
)
from core.logger import get_logger

logger = get_logger(__name__)

HBCE_FORMAT_VERSION = "1"
FILE_EXTENSION      = ".hbce"

# ── Internal helpers ──────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _jdump(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)

def _jload(s: str) -> dict:
    return json.loads(s)


# ═══════════════════════════════════════════════════════════════════════════════
#  Serializers — domain model → plain dict and back
# ═══════════════════════════════════════════════════════════════════════════════

def _device_to_dict(d: Device) -> dict:
    return {
        "name":           d.name,
        "vendor":         d.vendor,
        "model":          d.model,
        "firmware":       d.firmware,
        "address":        d.address,
        "protocol_id":    d.protocol_id or d.protocol.name.lower(),
        "params":         d.params,
        "description":    d.description,
        "bacnet_instance": d.bacnet_instance,
        "vendor_id":       d.vendor_id,
    }

def _device_from_dict(d: dict) -> Device:
    return Device(
        name            = d.get("name",""),
        vendor          = d.get("vendor",""),
        model           = d.get("model",""),
        firmware        = d.get("firmware",""),
        address         = d.get("address",""),
        protocol_id     = d.get("protocol_id",""),
        protocol        = ProtocolKind.from_str(d.get("protocol_id","")),
        params          = d.get("params",{}),
        description     = d.get("description",""),
        bacnet_instance = d.get("bacnet_instance"),
        vendor_id       = d.get("vendor_id"),
    )


def _program_to_dict(p: Program) -> dict:
    return {
        "program_name": p.program_name,
        "description":  p.description,
        "device_name":  p.device_name,
        "program_json": p.program_json,
        "created_at":   p.created_at,
        "updated_at":   p.updated_at,
        "created_by":   p.created_by,
    }

def _program_from_dict(d: dict) -> Program:
    return Program(
        program_name = d.get("program_name","Untitled"),
        description  = d.get("description",""),
        device_name  = d.get("device_name","Local"),
        program_json = d.get("program_json",{"blocks":[],"wires":[]}),
        created_at   = d.get("created_at",""),
        updated_at   = d.get("updated_at",""),
        created_by   = d.get("created_by",""),
    )


def _schedule_to_dict(s: Schedule) -> dict:
    return s.to_json()

def _schedule_from_dict(d: dict) -> Schedule:
    blocks = [
        ScheduleBlock(
            day=b["day"], start_min=b["start_min"],
            end_min=b["end_min"], value=b.get("value",True),
            label=b.get("label",""),
        )
        for b in d.get("blocks",[])
    ]
    return Schedule(
        schedule_name   = d.get("schedule_name",""),
        device_name     = d.get("device_name","Local"),
        object_instance = d.get("object_instance",0),
        blocks          = blocks,
        exceptions      = d.get("exceptions",[]),
        holidays        = d.get("holidays",[]),
        default_value   = d.get("default_value",False),
    )


def _backup_to_dict(b: BackupEntry) -> dict:
    return {
        "timestamp":   b.timestamp,
        "device_name": b.device_name,
        "device_id":   b.device_id,
        "backup_type": b.backup_type,
        "file_path":   b.file_path,
        "size_bytes":  b.size_bytes,
        "status":      b.status,
        "notes":       b.notes,
        "created_by":  b.created_by,
    }

def _backup_from_dict(d: dict) -> BackupEntry:
    return BackupEntry(
        timestamp   = d.get("timestamp",""),
        device_name = d.get("device_name",""),
        device_id   = d.get("device_id",0),
        backup_type = d.get("backup_type","manual"),
        file_path   = d.get("file_path",""),
        size_bytes  = d.get("size_bytes",0),
        status      = d.get("status","ok"),
        notes       = d.get("notes",""),
        created_by  = d.get("created_by",""),
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  ProjectFile — ZIP read/write
# ═══════════════════════════════════════════════════════════════════════════════

class ProjectFileError(Exception):
    pass


class ProjectFile:
    """
    Serialise and deserialise HBCE Project objects to/from .hbce ZIP files.

    .hbce ZIP layout:
        manifest.json
        devices.json
        programs/<safe_name>.json     (one per program)
        schedules/<safe_name>.json    (one per schedule)
        backups/<safe_name>.json      (one per backup entry)
        theme.json                    (optional)
    """

    # ── Save ──────────────────────────────────────────────────────────────────

    @classmethod
    def save(cls, project: Project, path: str,
             theme_json: Optional[dict] = None) -> None:
        """
        Write `project` to a .hbce ZIP file at `path`.
        Raises ProjectFileError on failure.
        """
        if not path.endswith(FILE_EXTENSION):
            path += FILE_EXTENSION

        try:
            from version import VERSION
            app_version = VERSION
        except ImportError:
            app_version = "unknown"

        manifest = {
            "format_version": HBCE_FORMAT_VERSION,
            "app_version":    app_version,
            "project_name":   project.name,
            "description":    project.description,
            "created":        project.created or _now(),
            "modified":       _now(),
            "device_count":   len(project.devices),
            "program_count":  len(project.programs),
            "schedule_count": len(project.schedules),
            "backup_count":   len(project.backups),
        }

        try:
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:

                # manifest
                zf.writestr("manifest.json", _jdump(manifest))

                # devices
                zf.writestr("devices.json",
                            _jdump([_device_to_dict(d) for d in project.devices]))

                # programs/
                for prog in project.programs:
                    safe = _safe_name(prog.program_name)
                    zf.writestr(f"programs/{safe}.json",
                                _jdump(_program_to_dict(prog)))

                # schedules/
                for sched in project.schedules:
                    safe = _safe_name(sched.schedule_name or f"sched_{id(sched)}")
                    zf.writestr(f"schedules/{safe}.json",
                                _jdump(_schedule_to_dict(sched)))

                # backups/
                for bk in project.backups:
                    safe = _safe_name(f"{bk.device_name}_{bk.timestamp}")
                    zf.writestr(f"backups/{safe}.json",
                                _jdump(_backup_to_dict(bk)))

                # theme (optional)
                if theme_json:
                    zf.writestr("theme.json", _jdump(theme_json))

        except Exception as e:
            raise ProjectFileError(f"Save failed: {e}") from e

        logger.info(f"Project saved: {path}  ({os.path.getsize(path)} bytes)")

    # ── Load ──────────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, path: str) -> Project:
        """
        Read a .hbce ZIP file and return a Project.
        Raises ProjectFileError on failure.
        """
        if not os.path.exists(path):
            raise ProjectFileError(f"File not found: {path}")

        try:
            with zipfile.ZipFile(path, "r") as zf:
                names = set(zf.namelist())

                # Manifest
                if "manifest.json" not in names:
                    raise ProjectFileError("Not a valid .hbce file (no manifest).")
                manifest = _jload(zf.read("manifest.json").decode())
                fmt_ver  = manifest.get("format_version","0")
                if fmt_ver != HBCE_FORMAT_VERSION:
                    logger.warning(
                        f"Project format version mismatch: "
                        f"file={fmt_ver}, expected={HBCE_FORMAT_VERSION}"
                    )

                # Devices
                devices = []
                if "devices.json" in names:
                    for dd in _jload(zf.read("devices.json").decode()):
                        try:
                            devices.append(_device_from_dict(dd))
                        except Exception as e:
                            logger.warning(f"Skipping device: {e}")

                # Programs
                programs = []
                for n in names:
                    if n.startswith("programs/") and n.endswith(".json"):
                        try:
                            programs.append(
                                _program_from_dict(_jload(zf.read(n).decode()))
                            )
                        except Exception as e:
                            logger.warning(f"Skipping program {n}: {e}")

                # Schedules
                schedules = []
                for n in names:
                    if n.startswith("schedules/") and n.endswith(".json"):
                        try:
                            schedules.append(
                                _schedule_from_dict(_jload(zf.read(n).decode()))
                            )
                        except Exception as e:
                            logger.warning(f"Skipping schedule {n}: {e}")

                # Backups
                backups = []
                for n in names:
                    if n.startswith("backups/") and n.endswith(".json"):
                        try:
                            backups.append(
                                _backup_from_dict(_jload(zf.read(n).decode()))
                            )
                        except Exception as e:
                            logger.warning(f"Skipping backup {n}: {e}")

        except zipfile.BadZipFile as e:
            raise ProjectFileError(f"Corrupt or invalid .hbce file: {e}") from e
        except ProjectFileError:
            raise
        except Exception as e:
            raise ProjectFileError(f"Load failed: {e}") from e

        project = Project(
            name        = manifest.get("project_name","Unnamed"),
            description = manifest.get("description",""),
            created     = manifest.get("created",""),
            modified    = manifest.get("modified",""),
            hbce_version= manifest.get("app_version",""),
            devices     = devices,
            programs    = programs,
            schedules   = schedules,
            backups     = backups,
        )
        logger.info(
            f"Project loaded: {path}  "
            f"({len(devices)}d / {len(programs)}p / {len(schedules)}s)"
        )
        return project

    # ── Convenience aliases ───────────────────────────────────────────────────

    @classmethod
    def export_zip(cls, project: Project, path: str,
                   theme_json: Optional[dict] = None) -> None:
        return cls.save(project, path, theme_json=theme_json)

    @classmethod
    def import_zip(cls, path: str) -> Project:
        return cls.load(path)

    # ── Quick metadata peek (no full load) ────────────────────────────────────

    @classmethod
    def peek_manifest(cls, path: str) -> dict:
        """Return manifest dict without loading the whole project."""
        try:
            with zipfile.ZipFile(path, "r") as zf:
                return _jload(zf.read("manifest.json").decode())
        except Exception as e:
            raise ProjectFileError(f"Cannot read manifest: {e}") from e

    # ── DB import / export helpers ────────────────────────────────────────────

    @classmethod
    def load_from_db(cls, db, project_id: int) -> Project:
        """
        Reconstruct a Project from the HBCE SQLite database.
        Pulls devices, programs, and schedules for the given project_id.
        """
        row = db.fetchone("SELECT * FROM projects WHERE id=?", (project_id,))
        if not row:
            raise ProjectFileError(f"No project with id={project_id}")

        project = Project(
            project_id  = row["id"],
            name        = row["name"],
            description = row.get("description",""),
            created     = row.get("created",""),
            modified    = row.get("modified",""),
        )

        # Devices
        dev_rows = db.fetchall(
            "SELECT * FROM devices WHERE project_id=?", (project_id,))
        for dr in dev_rows:
            project.devices.append(Device.from_db_row(dr))

        # Programs (not project-scoped in current schema — load all)
        try:
            prog_rows = db.fetchall(
                "SELECT * FROM programs ORDER BY updated_at DESC")
            for pr in prog_rows:
                project.programs.append(Program.from_db_row(pr))
        except Exception:
            pass   # programs table may not exist yet

        # Schedules
        try:
            sched_rows = db.fetchall(
                "SELECT * FROM schedules ORDER BY device_name, schedule_name")
            for sr in sched_rows:
                import json as _j
                sd = {}
                if sr.get("schedule_json"):
                    try: sd = _j.loads(sr["schedule_json"])
                    except Exception: pass
                if sd:
                    project.schedules.append(_schedule_from_dict(sd))
        except Exception:
            pass

        logger.info(f"Project loaded from DB: id={project_id}, name={project.name}")
        return project

    @classmethod
    def save_to_db(cls, db, project: Project) -> int:
        """
        Persist a Project back to SQLite.
        Returns the projects.id (inserts or updates).
        """
        now = _now()
        if project.project_id:
            db.update("UPDATE projects SET name=?, modified=? WHERE id=?",
                      (project.name, now, project.project_id))
            pid = project.project_id
        else:
            pid = db.insert(
                "INSERT INTO projects (name, created, modified) VALUES (?,?,?)",
                (project.name, now, now))
            project.project_id = pid

        logger.info(f"Project saved to DB: id={pid}")
        return pid


# ── Utility ───────────────────────────────────────────────────────────────────

def _safe_name(name: str) -> str:
    """Make a string safe for use as a zip entry filename."""
    safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in name)
    return safe.strip().replace(" ", "_")[:80] or "unnamed"
