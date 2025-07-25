import os
import subprocess
import json
import logging
import re
from datetime import datetime

# --------------------------
# CLEAN OUTPUT
# --------------------------
def clean_code_output(raw_output):
    """
    Cleans raw LLM output for project files.
    Removes:
    - 'assistant' block
    - '> EOF by user'
    - Markdown code fences
    """
    raw_output = re.sub(r'^.*assistant\s*', '', raw_output, flags=re.DOTALL)
    raw_output = re.sub(r'>\s*EOF.*$', '', raw_output, flags=re.MULTILINE)
    raw_output = re.sub(r"^```[a-zA-Z]*", "", raw_output.strip(), flags=re.MULTILINE)
    raw_output = re.sub(r"```$", "", raw_output, flags=re.MULTILINE)
    return raw_output.strip()


# --------------------------
# MAIN GENERATE FUNCTION
# --------------------------
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
        "cpp": [],
        "html": [],
        "docker": [],
        "sql": [],
        "placeholders": []
    }

    for idx, file_info in enumerate(files, start=1):
        path = file_info.get("path")
        abs_path = os.path.join(project_folder, path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        # ✅ Context-aware generation
        context_prompt = f"""
You are an expert software engineer. Generate the COMPLETE, production-ready content for the file:
{path}

### Project Description:
{original_prompt}

### Full Project Plan:
{json.dumps(plan, indent=2)}

### Rules:
- Output ONLY the code for {path}. NO markdown, NO commentary.
- Ensure imports, dependencies, and function names match other files.
- If it's HTML, include full valid structure.
- For config files (like requirements.txt), include complete dependencies.
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
            "--temp", "0.25",  # Lower temp for deterministic output
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

            # ✅ Run validation per file type
            if path.endswith(".py") and not cleaned_output.startswith("# ERROR"):
                validation_results["python"].append(validate_python(abs_path))
            elif path.endswith(".cpp") or path.endswith(".h"):
                validation_results["cpp"].append(validate_cpp(abs_path))
            elif path.endswith(".html"):
                validation_results["html"].append(validate_html(abs_path))
            elif path.lower() == "dockerfile":
                validation_results["docker"].append(validate_docker(abs_path))
            elif path.endswith(".sql"):
                validation_results["sql"].append(validate_sql(abs_path))

            # ✅ Check for placeholders
            placeholder_warn = scan_placeholders(abs_path)
            if placeholder_warn:
                validation_results["placeholders"].append(placeholder_warn)

        except Exception as e:
            logging.error(f"[Job {job_id}] Error generating {path}: {e}")
            with open(abs_path, "w") as out_file:
                out_file.write(f"# ERROR: {e}")

    # ✅ Write validation report
    write_validation_report(job_id, project_folder, validation_results, total_files)
    update_job_status(job_id, "completed", f"All {total_files} files generated successfully. See VALIDATION_REPORT.txt.")
    logging.info(f"[Job {job_id}] ✅ All files generated successfully.")
    return True


# --------------------------
# VALIDATION FUNCTIONS
# --------------------------
def validate_python(file_path):
    try:
        subprocess.check_output(["python3", "-m", "py_compile", file_path], stderr=subprocess.STDOUT)
        return f"[OK] {file_path}"
    except subprocess.CalledProcessError as e:
        return f"[ERROR] {file_path}\n  -> {e.output.decode('utf-8')}"


def validate_cpp(file_path):
    if not shutil.which("g++"):
        return f"[WARN] {file_path}\n  -> g++ not installed, skipping validation"
    try:
        subprocess.check_output(["g++", "-fsyntax-only", file_path], stderr=subprocess.STDOUT)
        return f"[OK] {file_path}"
    except subprocess.CalledProcessError as e:
        return f"[ERROR] {file_path}\n  -> {e.output.decode('utf-8')}"


def validate_html(file_path):
    try:
        result = subprocess.run(["tidy", "-q", "-e", file_path], capture_output=True, text=True)
        if result.returncode == 0:
            return f"[OK] {file_path}"
        return f"[WARN] {file_path}\n  -> {result.stderr.strip()}"
    except FileNotFoundError:
        return f"[WARN] {file_path}\n  -> tidy not installed"


def validate_docker(file_path):
    # Basic check: file is not empty and has FROM
    with open(file_path) as f:
        content = f.read()
    if "FROM" in content:
        return f"[OK] {file_path}"
    return f"[WARN] {file_path}\n  -> Missing FROM statement"


def validate_sql(file_path):
    try:
        result = subprocess.run(["sqlite3", ":memory:", f".read {file_path}"], capture_output=True, text=True)
        if result.returncode == 0:
            return f"[OK] {file_path}"
        return f"[ERROR] {file_path}\n  -> {result.stderr.strip()}"
    except Exception as e:
        return f"[WARN] {file_path}\n  -> sqlite3 not installed or failed: {e}"


def scan_placeholders(file_path):
    with open(file_path) as f:
        content = f.read()
    if re.search(r"\b(TODO|FIXME|PLACEHOLDER)\b", content, re.IGNORECASE):
        return f"[WARN] {file_path} contains placeholder text"
    return None


# --------------------------
# REPORT GENERATION
# --------------------------
def write_validation_report(job_id, project_folder, results, total_files):
    report_path = os.path.join(project_folder, "VALIDATION_REPORT.txt")
    with open(report_path, "w") as report:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        report.write("=============================\n")
        report.write(f"PROJECT VALIDATION REPORT\nJob ID: {job_id}\nGenerated: {now}\n")
        report.write("=============================\n\n")

        report.write("[ SUMMARY ]\n")
        report.write(f"✔ Total Files: {total_files}\n")
        for key, files in results.items():
            if files:
                report.write(f"✔ {key.upper()}: {len(files)} files checked\n")
        report.write("\n------------------------------------------------\n")

        for section, files in results.items():
            if files:
                report.write(f"[ {section.upper()} FILES ]\n")
                for f in files:
                    report.write(f"{f}\n")
                report.write("\n")

        if results["placeholders"]:
            report.write("------------------------------------------------\n")
            report.write("[ PLACEHOLDER WARNINGS ]\n")
            for warn in results["placeholders"]:
                report.write(f"{warn}\n")
