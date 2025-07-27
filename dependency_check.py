import logging
import os

# Critical external dependencies for C++ projects
CRITICAL_HEADERS = {
    "sqlite3.h": "libsqlite3-dev",
    "zlib.h": "zlib1g-dev",
    "boost/asio.hpp": "libboost-all-dev",
    "SDL2/SDL.h": "libsdl2-dev"
}

# Language runtime dependencies
LANG_DEPENDENCIES = {
    "python": ["python3", "python3-pip"],
    "go": ["golang"],
    "java": ["openjdk-17-jdk", "maven"]
}

def scan_missing_dependencies(project_folder):
    """
    Scan project for:
      - C++ critical headers
      - Detected languages
      - Language-specific dependency files
    Returns dict: {"missing": {...}, "install_command": "...", "notes": [...]}
    """
    logging.info("[DependencyCheck] Scanning for dependencies...")
    found_headers = {hdr: False for hdr in CRITICAL_HEADERS}
    detected_langs = set()
    notes = []

    has_pip = False
    has_go_mod = False
    has_pom = False

    for root, _, files in os.walk(project_folder):
        for file in files:
            file_path = os.path.join(root, file)
            # Check for C++ headers
            if file.endswith(".cpp") or file.endswith(".h"):
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    for header in CRITICAL_HEADERS:
                        if header in content:
                            found_headers[header] = True

            # Detect language files
            elif file.endswith(".py"):
                detected_langs.add("python")
            elif file.endswith(".go"):
                detected_langs.add("go")
            elif file.endswith(".java"):
                detected_langs.add("java")

            # Dependency files
            if file == "requirements.txt":
                has_pip = True
            if file == "go.mod":
                has_go_mod = True
            if file == "pom.xml":
                has_pom = True

    # Build missing system dependencies
    missing = {hdr: pkg for hdr, pkg in CRITICAL_HEADERS.items() if found_headers[hdr]}
    for lang in detected_langs:
        for pkg in LANG_DEPENDENCIES.get(lang, []):
            missing[f"{lang}-runtime"] = pkg

    # Notes for language-specific dependency managers
    if has_pip:
        notes.append("Install Python packages with: pip install -r requirements.txt")
    if has_go_mod:
        notes.append("Download Go modules with: go mod tidy")
    if has_pom:
        notes.append("Build Java project with Maven: mvn package")

    install_command = ""
    if missing:
        install_command = "apt-get update && apt-get install -y " + " ".join(missing.values())
        logging.warning(f"[DependencyCheck] Missing system dependencies: {missing}")
        logging.warning(f"[DependencyCheck] Suggested install command: {install_command}")
    else:
        logging.info("[DependencyCheck] No critical system dependencies detected.")

    if notes:
        logging.info(f"[DependencyCheck] Additional setup notes: {notes}")

    return {"missing": missing, "install_command": install_command, "notes": notes}

def log_dependency_fix_instructions(missing):
    if missing:
        logging.warning("[DependencyCheck] The following system packages are required:")
        for header, pkg in missing.items():
            logging.warning(f"  - {header}: Install `{pkg}`")
