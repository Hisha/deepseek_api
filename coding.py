import os
import subprocess
import json
import logging
import re
from datetime import datetime

# ===========================
# CLEANUP RAW MODEL OUTPUT
# ===========================
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

# ===========================
# MAIN FILE GENERATION LOGIC
# ===========================
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

    validation_results = []  # Collect validation output

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

            # ✅ Validate by file type
            validation_results.append(validate_file(abs_path))

        except Exception as e:
            logging.error(f"[Job {job_id}] Error generating {path}: {e}")
            with open(abs_path, "w") as out_file:
                out_file.write(f"# ERROR: {e}")

    # ✅ Write validation report
    write_validation_report(job_id, project_folder, validation_results)

    update_job_status(job_id, "completed", f"All {total_files} files generated successfully. See VALIDATION_REPORT.txt.")
    logging.info(f"[Job {job_id}] ✅ All files generated successfully.")
    return True

# ===========================
# VALIDATION LOGIC
# ===========================
def validate_file(file_path):
    """Validate files by type and return status string."""
    if file_path.endswith(".py"):
        return validate_python(file_path)
    elif file_path.endswith(".html"):
        return validate_html(file_path)
    elif file_path.lower() == "dockerfile":
        return validate_dockerfile(file_path)
    elif file_path.endswith(".sql"):
        return validate_sql(file_path)
    elif file_path.endswith(".cpp") or file_path.endswith(".hpp"):
        return validate_cpp(file_path)
    else:
        return f"[INFO] {file_path} (No validator available)"

def validate_python(file_path):
    try:
        subprocess.check_output(["python3", "-m", "py_compile", file_path], stderr=subprocess.STDOUT)
        return f"[OK] {file_path}"
    except subprocess.CalledProcessError as e:
        return f"[ERROR: Syntax] {file_path}\n  -> {e.output.decode('utf-8')}"

def validate_html(file_path):
    try:
        result = subprocess.run(["tidy", "-e", file_path], capture_output=True, text=True)
        if result.returncode == 0:
            return f"[OK] {file_path}"
        else:
            warnings = result.stderr.strip()
            return f"[INFO] {file_path}\n  -> {warnings}"
    except FileNotFoundError:
        return f"[INFO] {file_path} (tidy not installed)"

def validate_dockerfile(file_path):
    return f"[INFO] {file_path} (Dockerfile lint not implemented yet)"

def validate_sql(file_path):
    return f"[INFO] {file_path} (SQL validation not implemented yet)"

def validate_cpp(file_path):
    try:
        result = subprocess.run(["g++", "-fsyntax-only", file_path], capture_output=True, text=True)
        if result.returncode == 0:
            return f"[OK] {file_path}"
        else:
            if "No such file or directory" in result.stderr:
                missing = re.findall(r"fatal error: (.*): No such file", result.stderr)
                if missing:
                    return f"[ERROR: Missing Dependency] {file_path}\n  -> Missing dependency: {missing[0]}"
            return f"[ERROR: Syntax] {file_path}\n  -> {result.stderr.strip()}"
    except FileNotFoundError:
        return f"[INFO] {file_path} (g++ not installed)"

# ===========================
# REPORT GENERATOR
# ===========================
def write_validation_report(job_id, project_folder, results):
    report_path = os.path.join(project_folder, "VALIDATION_REPORT.txt")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(report_path, "w") as report:
        report.write("=============================\n")
        report.write(f"PROJECT VALIDATION REPORT\nJob ID: {job_id}\nGenerated: {timestamp}\n")
        report.write("=============================\n\n")

        # Group by type
        sections = {"PYTHON": [], "HTML": [], "DOCKERFILE": [], "SQL": [], "CPP": [], "OTHER": []}
        for r in results:
            if ".py" in r:
                sections["PYTHON"].append(r)
            elif ".html" in r:
                sections["HTML"].append(r)
            elif "Dockerfile" in r:
                sections["DOCKERFILE"].append(r)
            elif ".sql" in r:
                sections["SQL"].append(r)
            elif ".cpp" in r or ".hpp" in r:
                sections["CPP"].append(r)
            else:
                sections["OTHER"].append(r)

        for category, items in sections.items():
            if items:
                report.write(f"------------------------------------------------\n[ {category} FILES ]\n")
                for item in items:
                    report.write(item + "\n")
                report.write("\n")
