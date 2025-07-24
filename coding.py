import os
import subprocess
import json
import logging
import re

# ------------------------
# Helpers
# ------------------------
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


def auto_comment_non_code(content, ext):
    """
    Detects lines of descriptive English text that are NOT valid syntax and comments them.
    Applies to Python, Dockerfile, PHP, SQL, HTML, C++.
    """
    lines = content.splitlines()
    commented_lines = []
    comment_prefix = {
        ".py": "# ",
        ".php": "// ",
        ".sql": "-- ",
        ".html": "<!-- ",
        ".cpp": "// ",
        ".h": "// ",
        "Dockerfile": "# "
    }

    prefix = comment_prefix.get(ext, "# ")

    # Regex for non-code heuristic: alphabetic words without common code symbols
    non_code_pattern = re.compile(r"^[A-Za-z\s]+$")

    for line in lines:
        if non_code_pattern.match(line.strip()) and line.strip() != "":
            commented_lines.append(f"{prefix}{line.strip()}")
        else:
            commented_lines.append(line)
    return "\n".join(commented_lines)


# ------------------------
# Main Generation Function
# ------------------------
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

    validation_results = []  # Collect validation + cleanup logs

    for idx, file_info in enumerate(files, start=1):
        path = file_info.get("path")
        abs_path = os.path.join(project_folder, path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        # ✅ Context-aware prompt
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
                validation_results.append(f"[WARN] {path}: LLM returned insufficient content")

            # ✅ Auto-comment non-code text
            ext = os.path.splitext(path)[1]
            cleaned_output = auto_comment_non_code(cleaned_output, ext)

            # Save file
            with open(abs_path, "w") as out_file:
                out_file.write(cleaned_output)

            logging.info(f"[Job {job_id}] ✅ File saved: {path}")

            # ✅ Validate based on type
            validation_results.extend(validate_file(abs_path))

        except Exception as e:
            logging.error(f"[Job {job_id}] Error generating {path}: {e}")
            with open(abs_path, "w") as out_file:
                out_file.write(f"# ERROR: {e}")
            validation_results.append(f"[ERROR] {path}: {e}")

    # ✅ Write validation report
    report_path = os.path.join(project_folder, "VALIDATION_REPORT.txt")
    with open(report_path, "w") as report:
        if validation_results:
            report.write("\n".join(validation_results))
        else:
            report.write("Validation completed. No issues found.\n")

    update_job_status(job_id, "completed", f"All {total_files} files generated successfully. See VALIDATION_REPORT.txt.")
    logging.info(f"[Job {job_id}] ✅ All files generated successfully.")
    return True


# ------------------------
# Validation Functions
# ------------------------
def validate_file(file_path):
    """Validate file based on its extension."""
    ext = os.path.splitext(file_path)[1]
    results = []

    if ext == ".py":
        results.append(validate_python(file_path))
    elif ext == ".cpp":
        results.append(validate_cpp(file_path))
    elif ext == ".html":
        results.append(validate_html(file_path))
    else:
        results.append(f"[INFO] {file_path}: No validator for this file type.")
    return results


def validate_python(file_path):
    """Validate Python file syntax."""
    try:
        subprocess.check_output(["python3", "-m", "py_compile", file_path], stderr=subprocess.STDOUT)
        return f"[OK] {file_path} (Python syntax valid)"
    except subprocess.CalledProcessError as e:
        return f"[ERROR] {file_path} (Python syntax error)\n{e.output.decode('utf-8')}"


def validate_cpp(file_path):
    """Validate C++ file using g++ if available."""
    if shutil.which("g++"):
        try:
            subprocess.check_output(["g++", "-fsyntax-only", file_path], stderr=subprocess.STDOUT)
            return f"[OK] {file_path} (C++ syntax valid)"
        except subprocess.CalledProcessError as e:
            return f"[ERROR] {file_path} (C++ syntax error)\n{e.output.decode('utf-8')}"
    return f"[WARN] {file_path}: g++ not installed, skipping C++ validation."


def validate_html(file_path):
    """Validate HTML file using tidy if installed."""
    if shutil.which("tidy"):
        try:
            subprocess.run(["tidy", "-q", "-e", file_path], capture_output=True, text=True, check=True)
            return f"[OK] {file_path} (HTML valid)"
        except subprocess.CalledProcessError as e:
            return f"[WARN] {file_path} (HTML validation issues)\n{e.stderr.strip()}"
    return f"[WARN] {file_path}: tidy not installed, skipping HTML validation."
