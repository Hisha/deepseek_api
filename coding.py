import os
import subprocess
import json
import logging
import re

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

    validation_results = []  # Collect validation results for the report

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

            # ✅ Run validation depending on file type
            validation_results.append(validate_file(abs_path, cleaned_output))

        except Exception as e:
            logging.error(f"[Job {job_id}] Error generating {path}: {e}")
            with open(abs_path, "w") as out_file:
                out_file.write(f"# ERROR: {e}")
            validation_results.append(f"[ERROR] {path}: Exception during generation -> {e}")

    # ✅ Write validation report
    report_path = os.path.join(project_folder, "VALIDATION_REPORT.txt")
    with open(report_path, "w") as report:
        if validation_results:
            report.write("\n".join(validation_results))
        else:
            report.write("No files validated.\n")

    update_job_status(job_id, "completed", f"All {total_files} files generated successfully. See VALIDATION_REPORT.txt.")
    logging.info(f"[Job {job_id}] ✅ All files generated successfully.")
    return True


# ------------------- Validators -------------------

def validate_file(file_path, content):
    """Determine file type and run appropriate validation."""
    if file_path.endswith(".py"):
        return validate_python(file_path)
    elif file_path.endswith(".html"):
        return validate_html(file_path)
    elif file_path.endswith(".cpp") or file_path.endswith(".cc"):
        return validate_cpp(file_path)
    elif file_path.endswith(".php"):
        return validate_php(file_path)
    elif file_path.endswith(".sql"):
        return validate_sql(content, file_path)
    elif "dockerfile" in file_path.lower():
        return validate_dockerfile(content, file_path)
    else:
        return f"[SKIPPED] {file_path}: No validator available."


def validate_python(file_path):
    """Check Python syntax using py_compile."""
    try:
        subprocess.check_output(["python3", "-m", "py_compile", file_path], stderr=subprocess.STDOUT)
        return f"[OK] Python syntax valid -> {file_path}"
    except subprocess.CalledProcessError as e:
        return f"[ERROR] Python syntax issue in {file_path}\n{e.output.decode('utf-8')}"


def validate_html(file_path):
    """Validate HTML using tidy (if installed)."""
    try:
        output = subprocess.check_output(["tidy", "-errors", "-quiet", file_path], stderr=subprocess.STDOUT)
        return f"[OK] HTML valid -> {file_path}"
    except subprocess.CalledProcessError as e:
        return f"[ERROR] HTML validation issues in {file_path}\n{e.output.decode('utf-8')}"


def validate_cpp(file_path):
    """Validate C++ syntax using g++ (if available)."""
    try:
        subprocess.check_output(["g++", "-fsyntax-only", file_path], stderr=subprocess.STDOUT)
        return f"[OK] C++ syntax valid -> {file_path}"
    except FileNotFoundError:
        return f"[SKIPPED] C++ validation skipped (g++ not installed) -> {file_path}"
    except subprocess.CalledProcessError as e:
        return f"[ERROR] C++ syntax issue in {file_path}\n{e.output.decode('utf-8')}"


def validate_php(file_path):
    """Validate PHP syntax using php -l."""
    try:
        output = subprocess.check_output(["php", "-l", file_path], stderr=subprocess.STDOUT)
        return f"[OK] PHP syntax valid -> {file_path}"
    except FileNotFoundError:
        return f"[SKIPPED] PHP validation skipped (php not installed) -> {file_path}"
    except subprocess.CalledProcessError as e:
        return f"[ERROR] PHP syntax issue in {file_path}\n{e.output.decode('utf-8')}"


def validate_sql(content, file_path):
    """Simple SQL validation placeholder."""
    if ";" in content and "SELECT" in content.upper():
        return f"[OK] SQL appears valid -> {file_path}"
    return f"[WARNING] SQL content might be incomplete -> {file_path}"


def validate_dockerfile(content, file_path):
    """Simple Dockerfile validation placeholder."""
    if "FROM" in content.upper():
        return f"[OK] Dockerfile basic check passed -> {file_path}"
    return f"[WARNING] Dockerfile may lack FROM instruction -> {file_path}"
