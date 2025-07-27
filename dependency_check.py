import logging
import os
import re

# Critical external dependencies for C++ projects
CRITICAL_HEADERS = {
    "sqlite3.h": "libsqlite3-dev",
    "zlib.h": "zlib1g-dev",
    "boost/asio.hpp": "libboost-all-dev",
    "SDL2/SDL.h": "libsdl2-dev"
}

def scan_missing_dependencies(project_folder):
    """
    Scan all .cpp and .h files for critical headers.
    Returns a dict of {header: count} for missing includes.
    """
    logging.info("[DependencyCheck] Scanning for critical dependencies...")
    found_headers = {hdr: False for hdr in CRITICAL_HEADERS}

    for root, _, files in os.walk(project_folder):
        for file in files:
            if file.endswith(".cpp") or file.endswith(".h"):
                file_path = os.path.join(root, file)
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    for header in CRITICAL_HEADERS:
                        if header in content:
                            found_headers[header] = True

    missing = {hdr: pkg for hdr, pkg in CRITICAL_HEADERS.items() if found_headers[hdr]}
    if missing:
        logging.warning(f"[DependencyCheck] Missing system dependencies: {missing}")
    else:
        logging.info("[DependencyCheck] No critical dependencies detected.")

    return missing  # Example: {"sqlite3.h": "libsqlite3-dev", "SDL2/SDL.h": "libsdl2-dev"}

def log_dependency_fix_instructions(missing):
    """
    Log instructions for installing missing dependencies.
    """
    if missing:
        logging.warning("[DependencyCheck] The following system packages are required:")
        for header, pkg in missing.items():
            logging.warning(f"  - {header}: Install `{pkg}`")
        logging.warning("Install with: apt-get update && apt-get install -y " +
                        " ".join(missing.values()))
