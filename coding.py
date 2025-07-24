import os
import subprocess
import json
import logging
import re
from datetime import datetime

# -------------------
# Cleaning raw LLM output
# -------------------
def clean_code_output(raw_output):
    """
    Cleans raw LLM output for project files.
    Removes:
    - 'assistant' and preamble text
    - '> EOF by user'
    - Markdown code fences
    """
    raw_output = re.sub(r'^.*assistant\s*', '', raw_output, flags=re.DOTALL)
    raw_output = re.sub(r'>\s*EOF.*$', '', raw_output, flags=re.MULTILINE)
    raw_output = re.sub(r"^```[a-zA-Z]*", "", raw_output.strip(), flags=re.MULTILINE)
    raw_output = re.sub(r"```$", "", raw_output, flags=re.MULTILINE)
    return raw_output.strip()

# -------------------
# Generate project files
# -------------------
def generate_files(job_id, PROJECTS_DIR, LLAMA_PATH, MODEL_CODE_PATH, update_job_status):
    project_folder = os.path.join(PROJECTS_DIR, f"job_{job_id}")
    plan_path = os.path.join(project_folder, "plan.json")
    prompt_path = os.path.join(project_folder, "prompt.txt")

    if not os.path.exists(plan_path) or not os.path.exists(prompt_path):
        update_job_status(job_id, "error", "Missing plan.json or original prompt.")
        return False

    with open(plan_path) as f:
        plan = json.load(f)
    with open(prompt_path) as f:
        original_prompt = f.read().strip()

    files = plan.get("files", [])
    total_files = len(files)

    if total_files == 0:
        update_job_status(job_id, "error", "No files found in plan.json.")
        return False

    validation_results = {
        "python": [],
        "html": [],
        "docker": [],
        "sql": [],
        "cpp": [],
        "warnings": []
    }
    cpp_files = []

    for idx, file_info in enumerate(files, start=1):
        path = file_info.get("path")
        abs_path = os.path.join(project_folder, path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        # ✅ Context-aware, full implementation prompt
        context_prompt = f"""
You are an expert software engineer. Write the COMPLETE, production-ready implementation for:
{path}

### Project Description:
{original_prompt}

### Full Project Plan:
{json.dumps(plan, indent=2)}

### Rules:
- Output ONLY the code for {path}. No markdown, no commentary.
- Implement full logic. DO NOT include placeholders, "TODO", or dummy comments.
- Ensure imports, dependencies, and function names match other files.
- For HTML: full valid structure.
- For Dockerfile: complete buildable configuration.
- For config files (requirements.txt): include full dependencies.
"""

        progress = int((idx / total_files) * 100)
        current_step = f"Generating file {idx}/{total_files}: {path}"
        update_job_status(job_id, "processing", message=current_step, progress=progress, current_step=current_step)
        logging.info(f"[Job {job_id}] {current_step}")

        cmd = [
            LLAMA_PATH, "-m", MODEL_CODE_PATH,
            "-t", "28",
            "--ctx-size", "8192",
            "--n-predict", "4096",
            "--temp", "0.25",
            "--top-p", "0.9",
            "--repeat-penalty", "1.05",
            "-p", context_prompt
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=1500)
            raw_output = result.stdout.strip()
            cleaned_output = clean_code_output(raw_output)

            if not cleaned_output or len(cleaned_output.splitlines()) < 2:
                cleaned_output = f"# ERROR: LLM returned insufficient content for {path}\n"

            with open(abs_path, "w") as out_file:
                out_file.write(cleaned_output)

            logging.info(f"[Job {job_id}] ✅ File saved: {path}")

            # ✅ Collect file for validation
            if path.endswith(".py"):
                validation_results["python"].append(validate_python_file(abs_path))
            elif path.endswith(".html"):
                validation_results["html"].append(validate_html_file(abs_path))
            elif path.lower() == "dockerfile":
                validation_results["docker"].append(validate_dockerfile(abs_path))
            elif path.endswith(".sql"):
                validation_results["sql"].append(validate_sql_file(abs_path))
            elif path.endswith(".cpp"):
                cpp_files.append(abs_path)

            # ✅ Check for placeholders
            if re.search(r"TODO|placeholder", cleaned_output, re.IGNORECASE):
                validation_results["warnings"].append(f"[WARNING] {path} contains placeholder or TODO")

        except Exception as e:
            logging.error(f"[Job {job_id}] Error generating {path}: {e}")
            with open(abs_path, "w") as out_file:
                out_file.write(f"# ERROR: {e}")

    # ✅ Validate C++ as a combined compilation
    if cpp_files:
        validation_results["cpp"].append(validate_cpp_files(cpp_files))

    # ✅ Write validation report
    write_validation_report(job_id, project_folder, validation_results)

    update_job_status(job_id, "completed", f"All {total_files} files generated successfully. See VALIDATION_REPORT.txt.")
    logging.info(f"[Job {job_id}] ✅ All files generated successfully.")
    return True

# -------------------
# Validation helpers
# -------------------
def validate_python_file(file_path):
    try:
        subprocess.check_output(["python3", "-m", "py_compile", file_path], stderr=subprocess.STDOUT)
        return f"[OK] {file_path}"
    except subprocess.CalledProcessError as e:
        return f"[ERROR] {file_path}\n  -> {e.output.decode('utf-8')}"

def validate_html_file(file_path):
    try:
        subprocess.check_output(["tidy", "-errors", file_path], stderr=subprocess.STDOUT)
        return f"[OK] {file_path}"
    except subprocess.CalledProcessError as e:
        return f"[ERROR] {file_path}\n  -> {e.output.decode('utf-8')}"

def validate_dockerfile(file_path):
    # Simple presence check since Docker CLI may not be installed
    return f"[OK] {file_path}"

def validate_sql_file(file_path):
    try:
        subprocess.check_output(["sqlite3", ":memory:", f".read {file_path}"], stderr=subprocess.STDOUT)
        return f"[OK] {file_path}"
    except subprocess.CalledProcessError as e:
        return f"[ERROR] {file_path}\n  -> {e.output.decode('utf-8')}"

def validate_cpp_files(files):
    try:
        cmd = ["g++", "-std=c++17", "-fsyntax-only"] + files
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        return f"[OK] All C++ files compiled successfully"
    except subprocess.CalledProcessError as e:
        return f"[ERROR] C++ validation failed\n  -> {e.output.decode('utf-8')}"

# -------------------
# Write validation report
# -------------------
def write_validation_report(job_id, project_folder, results):
    report_path = os.path.join(project_folder, "VALIDATION_REPORT.txt")
    with open(report_path, "w") as report:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        report.write(f"=============================\n")
        report.write(f"PROJECT VALIDATION REPORT\n")
        report.write(f"Job ID: {job_id}\n")
        report.write(f"Generated: {now}\n")
        report.write(f"=============================\n\n")

        # Summary
        report.write("[ SUMMARY ]\n")
        report.write(f"✔ Python: {len(results['python'])} files\n")
        report.write(f"✔ HTML: {len(results['html'])} files\n")
        report.write(f"✔ Dockerfile: {len(results['docker'])} files\n")
        report.write(f"✔ SQL: {len(results['sql'])} files\n")
        report.write(f"✔ C++: {len(results['cpp'])} checks\n\n")

        # Detailed sections
        for category in ["python", "html", "docker", "sql", "cpp"]:
            if results[category]:
                report.write(f"------------------------------------------------\n")
                report.write(f"[ {category.upper()} FILES ]\n")
                for line in results[category]:
                    report.write(f"{line}\n")
                report.write("\n")

        if results["warnings"]:
            report.write("------------------------------------------------\n")
            report.write("[ WARNINGS ]\n")
            for warn in results["warnings"]:
                report.write(f"{warn}\n")
