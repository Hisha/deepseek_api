import os
import subprocess
import re
import logging
from datetime import datetime
import shutil

# ----------------------------
# Individual Validators
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

def validate_html(file_path):
    try:
        result = subprocess.run(["tidy", "-q", "-e", file_path], capture_output=True, text=True)
        return "[OK]" if result.returncode == 0 else f"[WARN] {result.stderr.strip()}"
    except FileNotFoundError:
        return "[WARN] tidy not installed"

def validate_docker(file_path):
    with open(file_path) as f:
        content = f.read()
    return "[OK]" if "FROM" in content else "[WARN] Missing FROM statement"

def validate_sql(file_path):
    try:
        result = subprocess.run(["sqlite3", ":memory:", f".read {file_path}"], capture_output=True, text=True)
        return "[OK]" if result.returncode == 0 else f"[ERROR] {result.stderr.strip()}"
    except Exception as e:
        return f"[WARN] sqlite3 not installed or failed: {e}"

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
    """
    Validate only code-related files. Skip plan.json, prompt.txt, etc.
    """
    logging.info(f"[Validation] Starting validation in {project_folder}")

    results = {}
    ignore_files = {"prompt.txt", "plan.json", "plan_raw.txt", "VALIDATION_REPORT.txt"}
    ignore_extensions = {".zip"}

    for root, _, files in os.walk(project_folder):
        for file in files:
            # ✅ Skip ignored files
            if file in ignore_files or any(file.endswith(ext) for ext in ignore_extensions):
                continue

            file_path = os.path.join(root, file)
            logging.info(f"[Validation] Checking file: {file_path}")

            # ✅ Validate based on type
            if file.endswith(".py"):
                results[file_path] = validate_python(file_path)
            elif file.endswith(".cpp") or file.endswith(".h"):
                results[file_path] = validate_cpp(file_path)
            elif file.endswith(".html"):
                results[file_path] = validate_html(file_path)
            elif file.lower() == "dockerfile":
                results[file_path] = validate_docker(file_path)
            elif file.endswith(".sql"):
                results[file_path] = validate_sql(file_path)
            else:
                # ✅ Non-code file that slipped through, mark as skipped
                results[file_path] = "[SKIPPED] Non-code file"

            # ✅ Check for placeholders
            placeholder = scan_placeholders(file_path)
            if placeholder:
                results[file_path] += f" | {placeholder}"

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
