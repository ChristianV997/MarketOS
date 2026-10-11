from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from pathlib import Path
from typing import Any

from .evidence_source_contract import EvidenceRecord

MAX_RECORDS = 10_000


def _project_root() -> Path:
    return Path.cwd().resolve()


def validate_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(dataset, dict): errors.append("dataset_must_be_object")
    if not dataset.get("dataset_id"): errors.append("dataset_id_required")
    if not dataset.get("source_name"): errors.append("source_name_required")
    if not isinstance(dataset.get("provenance"), dict) or not dataset.get("provenance"): errors.append("dataset_provenance_required")
    if not isinstance(dataset.get("records"), list): errors.append("records_must_be_list")
    elif len(dataset["records"]) > MAX_RECORDS: errors.append("record_limit_exceeded")
    return {"valid": not errors, "errors": errors}


def _confined_dataset_path(path: str) -> str:
    """Return the real absolute path of ``path`` if it stays under the project root.

    Relative paths are taken from the project root. Symlinks are resolved first, so a
    link inside the project that points outside is rejected. Confinement uses a path
    boundary check (``commonpath`` / ``relative_to``), not a plain string prefix, so
    sibling directories that share a name prefix cannot sneak through. A rejected path
    raises the same error whether or not it exists, so the result is not an existence
    oracle.
    """
    if not isinstance(path, str) or not path or "\x00" in path:
        raise ValueError("dataset_path_invalid")
    if ".." in Path(path).parts:
        raise ValueError("dataset_path_traversal_blocked")
    root_s = os.path.realpath(_project_root())
    candidate = Path(path) if Path(path).is_absolute() else Path(root_s) / path
    try:
        resolved_s = os.path.realpath(candidate)
    except (OSError, ValueError):
        raise ValueError("dataset_path_invalid") from None
    try:
        if os.path.commonpath([root_s, resolved_s]) != root_s:
            raise ValueError("dataset_path_outside_project_root")
        relative = Path(resolved_s).relative_to(root_s)
    except ValueError:
        raise ValueError("dataset_path_outside_project_root") from None
    if not relative.parts or relative == Path(".") or ".." in relative.parts:
        raise ValueError("dataset_path_outside_project_root")
    return resolved_s


def _read_regular_file(resolved: str) -> bytes:
    """Read a project-root-confined file through the descriptor that was actually opened.

    Path-boundary checks (``commonpath`` / ``relative_to``) run first and are kept as
    defense-in-depth. The bytes then come from an object opened under the project root
    without following symlinks: on POSIX every component is walked from a pinned root
    descriptor (``_read_regular_file_posix``); on Windows the handle is opened first and
    its final path is verified under the root before any read. ``O_NONBLOCK`` plus the
    regular-file check keep a FIFO or device from hanging or feeding the loader.
    Descriptors are always closed.
    """
    if not isinstance(resolved, str) or not resolved or "\x00" in resolved:
        raise ValueError("dataset_path_invalid")
    root_s = os.path.realpath(_project_root())

    try:
        if os.path.commonpath([root_s, resolved]) != root_s:
            raise ValueError("dataset_path_outside_project_root")
        relative_path = Path(resolved).relative_to(root_s)
    except ValueError:
        raise ValueError("dataset_path_outside_project_root") from None
    if not relative_path.parts or relative_path == Path(".") or ".." in relative_path.parts:
        raise ValueError("dataset_path_outside_project_root")

    # Rebuild the absolute path from root + relative without following symlinks so a
    # final-component swap stays at this path for O_NOFOLLOW to reject.
    confined = os.path.normpath(os.path.join(root_s, *relative_path.parts))
    try:
        if os.path.commonpath([root_s, confined]) != root_s:
            raise ValueError("dataset_path_outside_project_root")
        Path(confined).relative_to(root_s)
    except ValueError:
        raise ValueError("dataset_path_outside_project_root") from None

    if os.name == "nt":
        return _read_regular_file_windows(confined, root_s)
    return _read_regular_file_posix(root_s, relative_path.parts)


def _read_regular_file_posix(root_s: str, relative_parts: tuple[str, ...]) -> bytes:
    """Read one regular file by walking root-relative components from a pinned descriptor.

    Every component is opened with ``dir_fd`` relative to its already-open parent, and
    ``O_NOFOLLOW`` makes each open refuse a symlink. A symlink swapped into any
    component after the boundary check therefore fails closed instead of redirecting
    the read. The absolute path is never handed to ``os.open``, because POSIX ignores
    ``dir_fd`` for absolute paths. Plain ``openat`` semantics are enough; ``openat2`` is
    not required.
    """
    if os.open not in os.supports_dir_fd or not hasattr(os, "O_NOFOLLOW"):
        # Without dir_fd and O_NOFOLLOW the walk cannot refuse symlinks, so refuse to read.
        raise FileNotFoundError("dataset_not_found")
    nofollow = os.O_NOFOLLOW
    cloexec = getattr(os, "O_CLOEXEC", 0)
    dir_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow | cloexec
    file_flags = os.O_RDONLY | nofollow | getattr(os, "O_NONBLOCK", 0) | cloexec
    try:
        descriptor = _open_relative_file(root_s, relative_parts, dir_flags, file_flags)
    except OSError:
        raise FileNotFoundError("dataset_not_found") from None
    owned = True
    try:
        # A directory or FIFO fails here, before any read, with the same error as on Windows.
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise FileNotFoundError("dataset_not_found")
        with os.fdopen(descriptor, "rb") as handle:
            owned = False
            return handle.read()
    finally:
        if owned:
            os.close(descriptor)


def _open_relative_file(root_s: str, relative_parts: tuple[str, ...], dir_flags: int, file_flags: int) -> int:
    """Open ``relative_parts`` under ``root_s`` one component at a time, never following symlinks."""
    current = os.open(root_s, dir_flags)
    try:
        for name in relative_parts[:-1]:
            child = os.open(name, dir_flags, dir_fd=current)
            os.close(current)
            current = child
        return os.open(relative_parts[-1], file_flags, dir_fd=current)
    finally:
        os.close(current)


def _read_regular_file_windows(confined: str, root_s: str) -> bytes:
    """Read one regular file through a verified Win32 handle.

    Windows has no ``dir_fd``/``O_NOFOLLOW`` equivalent.  Open the path with
    ``FILE_FLAG_OPEN_REPARSE_POINT`` so a final-component swap is inspected as
    the reparse point itself, then bind the read to that same handle and verify
    its final path remains under the project root.  The final-path check also
    catches an intermediate junction/reparse-point race.
    """
    import ctypes
    import msvcrt
    from ctypes import wintypes

    generic_read = 0x80000000
    share_read = 0x00000001
    share_write = 0x00000002
    share_delete = 0x00000004
    open_existing = 3
    backup_semantics = 0x02000000
    open_reparse_point = 0x00200000
    invalid_handle = ctypes.c_void_p(-1).value
    file_attribute_reparse_point = 0x00000400
    file_attribute_directory = 0x00000010

    class _ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", wintypes.FILETIME),
            ("ftLastAccessTime", wintypes.FILETIME),
            ("ftLastWriteTime", wintypes.FILETIME),
            ("dwVolumeSerialNumber", wintypes.DWORD),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("nNumberOfLinks", wintypes.DWORD),
            ("nFileIndexHigh", wintypes.DWORD),
            ("nFileIndexLow", wintypes.DWORD),
        ]

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ByHandleFileInformation),
    ]
    kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel32.GetFinalPathNameByHandleW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.CreateFileW(
        confined,
        generic_read,
        share_read | share_write | share_delete,
        None,
        open_existing,
        backup_semantics | open_reparse_point,
        None,
    )
    if handle is None or handle == invalid_handle:
        raise FileNotFoundError("dataset_not_found")

    fd = -1
    try:
        info = _ByHandleFileInformation()
        if not kernel32.GetFileInformationByHandle(handle, ctypes.pointer(info)):
            raise FileNotFoundError("dataset_not_found")
        if info.dwFileAttributes & (file_attribute_reparse_point | file_attribute_directory):
            raise FileNotFoundError("dataset_not_found")

        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        handle = None
        final_buffer = ctypes.create_unicode_buffer(32768)
        final_length = kernel32.GetFinalPathNameByHandleW(
            wintypes.HANDLE(msvcrt.get_osfhandle(fd)), final_buffer, len(final_buffer), 0
        )
        if not final_length or final_length >= len(final_buffer):
            raise FileNotFoundError("dataset_not_found")
        final_path = final_buffer.value
        if final_path.startswith("\\\\?\\UNC\\"):
            final_path = "\\\\" + final_path[8:]
        elif final_path.startswith("\\\\?\\"):
            final_path = final_path[4:]
        try:
            if os.path.commonpath([os.path.normcase(os.path.realpath(root_s)), os.path.normcase(os.path.realpath(final_path))]) != os.path.normcase(os.path.realpath(root_s)):
                raise ValueError
        except (OSError, ValueError):
            raise FileNotFoundError("dataset_not_found") from None

        with os.fdopen(fd, "rb") as handle_file:
            fd = -1
            if not stat.S_ISREG(os.fstat(handle_file.fileno()).st_mode):
                raise FileNotFoundError("dataset_not_found")
            return handle_file.read()
    except BaseException:
        if fd >= 0:
            os.close(fd)
        elif handle is not None:
            kernel32.CloseHandle(handle)
        raise


def load_local_evidence_dataset(path: str) -> dict[str, Any]:
    dataset = json.loads(_read_regular_file(_confined_dataset_path(path)).decode("utf-8"))
    validation = validate_dataset(dataset)
    if not validation["valid"]: raise ValueError(";".join(validation["errors"]))
    return dataset


def parse_evidence_records(dataset: dict[str, Any]) -> list[EvidenceRecord]:
    validation = validate_dataset(dataset)
    if not validation["valid"]: raise ValueError(";".join(validation["errors"]))
    source_name = str(dataset["source_name"])
    records: list[EvidenceRecord] = []
    for index, raw in enumerate(dataset["records"][:MAX_RECORDS]):
        if not isinstance(raw, dict): continue
        provenance = dict(dataset["provenance"])
        provenance.setdefault("dataset_id", dataset["dataset_id"])
        provenance.setdefault("source_path_type", "local_dataset")
        if not provenance: continue
        seed = f"{dataset['dataset_id']}:{index}:{raw.get('entity_type')}:{raw.get('entity_name')}:{raw.get('signal_type')}"
        evidence = {"evidence_id": f"evidence_{hashlib.sha256(seed.encode()).hexdigest()[:16]}", "source_name": source_name, "source_type": "fixture" if provenance.get("type") == "synthetic_fixture" else "local_file", "entity_type": raw.get("entity_type", ""), "entity_name": raw.get("entity_name", ""), "signal_type": raw.get("signal_type", ""), "value": raw.get("value"), "weight": raw.get("weight", 1.0), "confidence": raw.get("confidence", 0.0), "timestamp": float(raw.get("timestamp", time.time())), "provenance": provenance, "metadata": raw.get("metadata", {})}
        try: records.append(EvidenceRecord.from_dict(evidence))
        except (TypeError, ValueError): continue
    return records
