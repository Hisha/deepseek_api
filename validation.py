import os
import subprocess
import re
import logging
from datetime import datetime
import shutil

# ----------------------------
# Config: Invalid & External Dependencies
# ----------------------------
INVALID_PACKAGES = {
    "sqlite3", "sys", "os", "json", "re", "logging", "subprocess", "argparse"
}

# Map of external headers → package hints for INSTALL.md
DEPENDENCY_MAP = {
    "sqlite3.h": "libsqlite3-dev",
    "SDL2/SDL.h": "libsdl2-dev",
    "boost/asio.hpp": "libboost-all-dev",
    "zlib.h": "zlib1g-dev"
}

# Directories and file types to ignore
IGNORE_DIRS = {"__pycache__", ".git", "node_modules", "bin", "obj", "target"}
BINARY_EXTENSIONS = {
    ".pyc", ".pyo", ".exe", ".dll", ".so", ".o", ".a", ".lib", ".class", ".jar"
}
IGNORE_FILES = {"prompt.txt", "plan.json", "plan_raw.txt", "VALIDATION_REPORT.txt"}
IGNORE_EXTENSIONS = {".zip", ".tar", ".gz"}

# ----------------------------
# Utility Functions
# ----------------------------
def is_binary_file(file_path):
    """Check if a file should be considered binary by extension or content."""
    if any(file_path.endswith(ext) for ext in BINARY_EXTENSIONS):
        return True
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(1024)
            if b"\0" in chunk:  # Null byte indicates binary
                return True
    except Exception:
        return True
    return False

def safe_read_text(file_path):
    """Read file content safely as text or return None if binary/unreadable."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        logging.warning(f"[Validation] Skipping binary/unreadable file: {file_path}")
        return None
    except Exception as e:
        logging.error(f"[Validation] Error reading file {file_path}: {e}")
        return None

# ----------------------------
# Validators
# ----------------------------
def validate_python(file_path):
    try:
        subprocess.check_output(["python3", "-m", "py_compile", file_path], stderr=subprocess.STDOUT)
        return "[OK]"
    except subprocess.CalledProcessError as e:
        return f"[ERROR] {e.output.decode('utf-8')}"

def validate_python_requirements(project_folder):
    req_path = os.path.join(project_folder, "requirements.txt")
    if os.path.exists(req_path):
        try:
            result = subprocess.run(["pip", "check"], capture_output=True, text=True)
            return "[OK]" if result.returncode == 0 else f"[WARN] {result.stdout.strip()}"
        except FileNotFoundError:
            return "[WARN] pip not installed"
    return None

def validate_cpp(file_path, missing_deps):
    content = safe_read_text(file_path)
    if content is None:
        return "[SKIPPED] Binary or unreadable file"

    for header, pkg in DEPENDENCY_MAP.items():
        if header in content:
            header_path = header.split("/")[0]
            if not os.path.exists(f"/usr/include/{header_path}"):
                missing_deps.add((header, pkg))

    if not shutil.which("g++"):
        return "[WARN] g++ not installed"

    try:
        subprocess.check_output(["g++", "-fsyntax-only", "-Wno-error", "-I./include", file_path], stderr=subprocess.STDOUT)
        return "[OK]"
    except subprocess.CalledProcessError as e:
        error_msg = e.output.decode("utf-8")
        if "No such file or directory" in error_msg:
            return "[WARN] Missing includes detected (check INSTALL.md)"
        return f"[ERROR] {error_msg}"

def validate_go(file_path, project_folder):
    if not shutil.which("go"):
        return "[WARN] Go not installed"
    if not os.path.exists(os.path.join(project_folder, "go.mod")):
        return "[WARN] Missing go.mod file"
    try:
        subprocess.check_output(["go", "build", file_path], stderr=subprocess.STDOUT)
        return "[OK]"
    except subprocess.CalledProcessError as e:
        return f"[ERROR] {e.output.decode('utf-8')}"

def validate_java(file_path, project_folder):
    if not shutil.which("javac"):
        return "[WARN] javac not installed"
    try:
        subprocess.check_output(["javac", file_path], stderr=subprocess.STDOUT)
        return "[OK]"
    except subprocess.CalledProcessError as e:
        return f"[ERROR] {e.output.decode('utf-8')}"

def validate_html(file_path):
    try:
        result = subprocess.run(["tidy", "-q", "-e", file_path], capture_output=True, text=True)
        return "[OK]" if result.returncode == 0 else f"[WARN] {result.stderr.strip()}"
    except FileNotFoundError:
        return "[WARN] tidy not installed"

def validate_docker(file_path):
    content = safe_read_text(file_path)
    if not content:
        return "[SKIPPED] Binary or unreadable file"
    issues = []
    if "FROM" not in content:
        issues.append("Missing FROM statement")
    if "CMD" not in content and "ENTRYPOINT" not in content:
        issues.append("Missing CMD or ENTRYPOINT")
    return "[OK]" if not issues else f"[WARN] {'; '.join(issues)}"

def validate_cmake(file_path):
    content = safe_read_text(file_path)
    if not content:
        return "[SKIPPED] Binary or unreadable file"
    issues = []
    if "include_directories" not in content:
        issues.append("Missing include_directories()")
    if "find_package(SQLite3" not in content:
        issues.append("Missing find_package(SQLite3 REQUIRED)")
    return "[OK]" if not issues else f"[WARN] {'; '.join(issues)}"

def validate_sql(file_path):
    try:
        result = subprocess.run(["sqlite3", ":memory:", f".read {file_path}"], capture_output=True, text=True)
        return "[OK]" if result.returncode == 0 else f"[ERROR] {result.stderr.strip()}"
    except Exception as e:
        return f"[WARN] sqlite3 not installed or failed: {e}"

def validate_requirements(file_path):
    invalid_lines = []
    content = safe_read_text(file_path)
    if not content:
        return "[SKIPPED] Binary or unreadable file"
    try:
        for line in content.splitlines():
            pkg = line.strip().split("==")[0]
            if pkg in INVALID_PACKAGES:
                invalid_lines.append(pkg)
        if invalid_lines:
            return f"[ERROR] Invalid packages in requirements.txt: {', '.join(invalid_lines)}"
        return "[OK]"
    except Exception as e:
        return f"[ERROR] Failed to validate requirements.txt: {e}"

def scan_placeholders(file_path):
    content = safe_read_text(file_path)
    if not content:
        return None
    if re.search(r"\b(TODO|FIXME|PLACEHOLDER)\b", content, re.IGNORECASE):
        return "[WARN] Placeholder text found"
    return None

# ----------------------------
# Main Validation Logic
# ----------------------------
def validate_project(project_folder):
    logging.info(f"[Validation] Starting validation in {project_folder}")
    results = {}
    missing_deps = set()

    for root, dirs, files in os.walk(project_folder):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for file in files:
            if file in IGNORE_FILES or any(file.endswith(ext) for ext in IGNORE_EXTENSIONS):
                continue
            file_path = os.path.join(root, file)
            if is_binary_file(file_path):
                results[file_path] = "[SKIPPED] Binary file"
                continue

            logging.info(f"[Validation] Checking file: {file_path}")

            if file.endswith(".py"):
                results[file_path] = validate_python(file_path)
            elif file.endswith(".cpp") or file.endswith(".h"):
                results[file_path] = validate_cpp(file_path, missing_deps)
            elif file.endswith(".go"):
                results[file_path] = validate_go(file_path, project_folder)
            elif file.endswith(".java"):
                results[file_path] = validate_java(file_path, project_folder)
            elif file.endswith(".html"):
                results[file_path] = validate_html(file_path)
            elif file.lower() == "dockerfile":
                results[file_path] = validate_docker(file_path)
            elif file.lower() == "cmakelists.txt":
                results[file_path] = validate_cmake(file_path)
            elif file.endswith(".sql"):
                results[file_path] = validate_sql(file_path)
            elif file == "requirements.txt":
                results[file_path] = validate_requirements(file_path)
            else:
                results[file_path] = "[SKIPPED] Non-code file"

            placeholder = scan_placeholders(file_path)
            if placeholder:
                results[file_path] += f" | {placeholder}"

    # ✅ Check Python dependencies if applicable
    py_dep_check = validate_python_requirements(project_folder)
    if py_dep_check:
        results["PythonDependencies"] = py_dep_check

    # ✅ Generate INSTALL.md with missing dependencies
    if missing_deps:
        install_path = os.path.join(project_folder, "INSTALL.md")
        with open(install_path, "w") as f:
            f.write("# Project Dependencies\n\nInstall the following packages before building:\n\n")
            for header, pkg in sorted(missing_deps):
                f.write(f"- `{header}` → Install `{pkg}`\n")
        logging.info(f"[Validation] INSTALL.md generated with {len(missing_deps)} dependencies.")

    logging.info(f"[Validation] Completed validation for {len(results)} files.")
    return results

# ----------------------------
# Report Writer
# ----------------------------
def write_validation_report(project_folder, job_id, validation_results):
    report_path = os.path.join(project_folder, "VALIDATION_REPORT.txt")
    install_path = os.path.join(project_folder, "INSTALL.md")
    with open(report_path, "w") as report:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        report.write(f"=== VALIDATION REPORT for Job {job_id} ===\nGenerated: {now}\n\n")
        for file_path, result in validation_results.items():
            report.write(f"{file_path}: {result}\n")
        if os.path.exists(install_path):
            report.write("\nNOTE: Missing dependencies detected. See INSTALL.md for installation instructions.\n")
    logging.info(f"[Validation] Report generated: {report_path}")
    return report_path
