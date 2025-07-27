import logging
import os

# Critical external dependencies for C++ projects
CRITICAL_HEADERS = {
    "sqlite3.h": "libsqlite3-dev",
    "zlib.h": "zlib1g-dev",
    "boost/asio.hpp": "libboost-all-dev",
    "SDL2/SDL.h": "libsdl2-dev"
}

# For other languages
LANG_DEPENDENCIES = {
    "python": ["python3", "pip"],
    "go": ["golang"],
    "java": ["openjdk-17-jdk", "maven"]
}

def scan_missing_dependencies(project_folder):
    """
    Scan all .cpp and .h files for critical headers.
    Also note language-related dependencies.
    Returns dict: {"missing": {...}, "install_command": "..."}
    """
    logging.info("[DependencyCheck] Scanning for critical dependencies...")
    found_headers = {hdr: False for hdr in CRITICAL_HEADERS}
    detected_langs = set()

    for root, _, files in os.walk(project_folder):
        for file in files:
            if file.endswith(".cpp") or file.endswith(".h"):
                file_path = os.path.join(root, file)
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    for header in CRITICAL_HEADERS:
                        if header in content:
                            found_headers[header] = True
            elif file.endswith(".py"):
                detected_langs.add("python")
            elif file.endswith(".go"):
                detected_langs.add("go")
            elif file.endswith(".java"):
                detected_langs.add("java")

    missing = {hdr: pkg for hdr, pkg in CRITICAL_HEADERS.items() if found_headers[hdr]}
    for lang in detected_langs:
        for pkg in LANG_DEPENDENCIES.get(lang, []):
            missing[f"{lang}-runtime"] = pkg

    install_command = ""
    if missing:
        install_command = "apt-get update && apt-get install -y " + " ".join(missing.values())
        logging.warning(f"[DependencyCheck] Missing system dependencies: {missing}")
        logging.warning(f"[DependencyCheck] Suggested install command: {install_command}")
    else:
        logging.info("[DependencyCheck] No critical dependencies detected.")

    return {"missing": missing, "install_command": install_command}

def log_dependency_fix_instructions(missing):
    if missing:
        logging.warning("[DependencyCheck] The following system packages are required:")
        for header, pkg in missing.items():
            logging.warning(f"  - {header}: Install `{pkg}`")
