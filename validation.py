import os
import subprocess
import re
import logging
from datetime import datetime
import shutil

INVALID_PACKAGES = {
    "sqlite3", "sys", "os", "json", "re", "logging", "subprocess", "argparse"
}

# ----------------------------
# Validators for file types
# ----------------------------
def validate_python(file_path):
    try:
        subprocess.check_output(["python3", "-m", "py_compile", file_path], stderr=subprocess.STDOUT)
        return "[OK]"
    except subprocess.CalledProcessError as e:
        return f"[ERROR] {e.output.decode('utf-8')}"

def validate_cpp(file_path):
    if not shutil.which("g++"):
        return "[WARN] g++ not installed"
    try:
        subprocess.check_output(["g++", "-fsyntax-only", file_path], stderr=subprocess.STDOUT)
        return "[OK]"
    except subprocess.CalledProcessError as e:
        return f"[ERROR] {e.output.decode('utf-8')}"

def validate_go(file_path):
    if not shutil.which("go"):
        return "[WARN] Go not installed"
    try:
        subprocess.check_output(["go", "build", file_path], stderr=subprocess.STDOUT)
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
    with open(file_path) as f:
        content = f.read()

    issues = []
    if "FROM" not in content:
        issues.append("Missing FROM statement")
    if "CMD" not in content and "ENTRYPOINT" not in content:
        issues.append("Missing CMD or ENTRYPOINT")
    if "RUN cmake" not in content and "RUN make" not in content:
        issues.append("Missing C++ build step")

    return "[OK]" if not issues else f"[WARN] {'; '.join(issues)}"

def validate_cmake(file_path):
    with open(file_path) as f:
        content = f.read()

    issues = []
    if "include_directories" not in content:
        issues.append("Missing include_directories()")
    if "find_package(SQLite3" not in content:
        issues.append("Missing find_package(SQLite3 REQUIRED)")

    return "[OK]" if not issues else f"[WARN] {'; '.join(issues)}"

def validate_sqlite_integration(project_folder):
    schema_exists = False
    cpp_uses_sqlite = False

    for root, _, files in os.walk(project_folder):
        if "schema.sql" in files:
            schema_exists = True
        for file in files:
            if file.endswith(".cpp"):
                with open(os.path.join(root, file)) as f:
                    if "sqlite3.h" in f.read():
                        cpp_uses_sqlite = True

    if schema_exists and not cpp_uses_sqlite:
        return "[WARN] SQLite schema exists but no C++ code includes sqlite3.h"
    return None

def validate_sql(file_path):
    try:
        result = subprocess.run(["sqlite3", ":memory:", f".read {file_path}"], capture_output=True, text=True)
        return "[OK]" if result.returncode == 0 else f"[ERROR] {result.stderr.strip()}"
    except Exception as e:
        return f"[WARN] sqlite3 not installed or failed: {e}"

def validate_requirements(file_path):
    invalid_lines = []
    try:
        with open(file_path) as f:
            for line in f:
                pkg = line.strip().split("==")[0]
                if pkg in INVALID_PACKAGES:
                    invalid_lines.append(pkg)
        if invalid_lines:
            return f"[ERROR] Invalid packages in requirements.txt: {', '.join(invalid_lines)}"
        return "[OK]"
    except Exception as e:
        return f"[ERROR] Failed to validate requirements.txt: {e}"

def scan_placeholders(file_path):
    with open(file_path) as f:
        content = f.read()
    if re.search(r"\b(TODO|FIXME|PLACEHOLDER)\b", content, re.IGNORECASE):
        return "[WARN] Placeholder text found"
    return None

# ----------------------------
# Main Validation Logic
# ----------------------------
def validate_project(project_folder):
    logging.info(f"[Validation] Starting validation in {project_folder}")
    results = {}

    ignore_files = {"prompt.txt", "plan.json", "plan_raw.txt", "VALIDATION_REPORT.txt"}
    ignore_extensions = {".zip"}

    for root, _, files in os.walk(project_folder):
        for file in files:
            if file in ignore_files or any(file.endswith(ext) for ext in ignore_extensions):
                continue

            file_path = os.path.join(root, file)
            logging.info(f"[Validation] Checking file: {file_path}")

            if file.endswith(".py"):
                results[file_path] = validate_python(file_path)
            elif file.endswith(".cpp") or file.endswith(".h"):
                results[file_path] = validate_cpp(file_path)
            elif file.endswith(".go"):
                results[file_path] = validate_go(file_path)
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

    sqlite_warn = validate_sqlite_integration(project_folder)
    if sqlite_warn:
        results["SQLiteIntegrationCheck"] = sqlite_warn

    logging.info(f"[Validation] Completed validation for {len(results)} files.")
    return results

# ----------------------------
# Report Writer
# ----------------------------
def write_validation_report(project_folder, job_id, validation_results):
    report_path = os.path.join(project_folder, "VALIDATION_REPORT.txt")
    with open(report_path, "w") as report:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        report.write(f"=== VALIDATION REPORT for Job {job_id} ===\nGenerated: {now}\n\n")
        for file_path, result in validation_results.items():
            report.write(f"{file_path}: {result}\n")
    logging.info(f"[Validation] Report generated: {report_path}")
    return report_path
