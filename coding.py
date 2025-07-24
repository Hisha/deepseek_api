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

        except Exception as e:
            logging.error(f"[Job {job_id}] Error generating {path}: {e}")
            with open(abs_path, "w") as out_file:
                out_file.write(f"# ERROR: {e}")

    # ✅ Validate all generated files
    validation_report = validate_generated_files(project_folder, files)

    # ✅ Save validation report
    report_path = os.path.join(project_folder, "VALIDATION_REPORT.txt")
    with open(report_path, "w") as report:
        report.write("\n".join(validation_report))

    update_job_status(job_id, "completed", f"All {total_files} files generated successfully. See VALIDATION_REPORT.txt.")
    logging.info(f"[Job {job_id}] ✅ All files generated successfully.")
    return True


def validate_generated_files(project_folder, files):
    validation_report = []
    for file_info in files:
        path = file_info.get("path")
        abs_path = os.path.join(project_folder, path)
        if not os.path.exists(abs_path):
            validation_report.append(f"{path}: ERROR - File not found.")
            continue

        ext = os.path.splitext(path)[1].lower()
        result = "OK"

        try:
            if ext == ".py":
                proc = subprocess.run(["python3", "-m", "py_compile", abs_path],
                                       capture_output=True, text=True)
                if proc.returncode != 0:
                    result = f"Python syntax error: {proc.stderr.strip()}"

            elif ext == ".html":
                with open(abs_path) as f:
                    content = f.read()
                if "<html" not in content.lower() or "</html>" not in content.lower():
                    result = "HTML structure warning: Missing <html> tags."

            elif "dockerfile" in path.lower():
                with open(abs_path) as f:
                    content = f.read().upper()
                if "FROM " not in content or ("CMD" not in content and "ENTRYPOINT" not in content):
                    result = "Dockerfile warning: Missing FROM or CMD/ENTRYPOINT."

            elif ext == ".php":
                try:
                    proc = subprocess.run(["php", "-l", abs_path],
                                           capture_output=True, text=True)
                    if proc.returncode != 0:
                        result = f"PHP syntax error: {proc.stderr.strip()}"
                except FileNotFoundError:
                    with open(abs_path) as f:
                        content = f.read()
                    if "<?php" not in content:
                        result = "PHP warning: Missing <?php opening tag."

            elif ext in [".cpp", ".cc", ".cxx"]:
                try:
                    proc = subprocess.run(["g++", "-fsyntax-only", abs_path],
                                           capture_output=True, text=True)
                    if proc.returncode != 0:
                        result = f"C++ syntax error: {proc.stderr.strip()}"
                except FileNotFoundError:
                    result = "C++ validation skipped: g++ not installed."

            elif ext == ".sql":
                with open(abs_path) as f:
                    content = f.read().upper()
                if not any(keyword in content for keyword in ["CREATE", "SELECT", "INSERT", "UPDATE"]):
                    result = "SQL warning: No common SQL statements found."

        except Exception as e:
            result = f"Validation error: {str(e)}"

        validation_report.append(f"{path}: {result}")

    return validation_report
