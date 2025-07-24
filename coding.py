import os
import subprocess
import json
import logging
import re
from datetime import datetime

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

    validation_results = {
        "Python": [],
        "HTML": [],
        "Dockerfile": [],
        "SQL": [],
        "C++": []
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

            # ✅ Validate based on file type
            if path.endswith(".py"):
                validation_results["Python"].append(validate_python_file(abs_path))
            elif path.endswith(".html"):
                validation_results["HTML"].append(validate_html_file(abs_path))
            elif path.lower() == "dockerfile":
                validation_results["Dockerfile"].append(validate_dockerfile(abs_path))
            elif path.endswith(".sql"):
                validation_results["SQL"].append(validate_sql_file(abs_path))
            elif path.endswith(".cpp"):
                validation_results["C++"].append(validate_cpp_file(abs_path))

        except Exception as e:
            logging.error(f"[Job {job_id}] Error generating {path}: {e}")
            with open(abs_path, "w") as out_file:
                out_file.write(f"# ERROR: {e}")

    # ✅ Write enhanced validation report
    report_path = os.path.join(project_folder, "VALIDATION_REPORT.txt")
    with open(report_path, "w") as report:
        report.write("=====================================\n")
        report.write("PROJECT VALIDATION REPORT\n")
        report.write(f"Job ID: {job_id}\n")
        report.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        report.write("=====================================\n\n")

        # Summary
        report.write("[ SUMMARY ]\n")
        for section, results in validation_results.items():
            ok_count = sum(1 for r in results if r.startswith("[OK]"))
            error_count = sum(1 for r in results if r.startswith("[ERROR]"))
            report.write(f"✔ {section}: {len(results)} files validated ({ok_count} OK, {error_count} ERROR)\n")
        report.write("\n")

        # Detailed sections
        for section, results in validation_results.items():
            if results:
                report.write(f"------------------------------------------------\n[{section.upper()} FILES]\n")
                for r in results:
                    report.write(r + "\n")
        report.write("\n")

    update_job_status(job_id, "completed", f"All {total_files} files generated successfully. See VALIDATION_REPORT.txt.")
    logging.info(f"[Job {job_id}] ✅ All files generated successfully.")
    return True


# ----------------- VALIDATORS -----------------
def validate_python_file(file_path):
    try:
        subprocess.check_output(["python3", "-m", "py_compile", file_path], stderr=subprocess.STDOUT)
        return f"[OK] {file_path}"
    except subprocess.CalledProcessError as e:
        return f"[ERROR] {file_path}\n{e.output.decode('utf-8')}"


def validate_html_file(file_path):
    try:
        with open(file_path, "r") as f:
            content = f.read()
        if "<html" in content.lower() and "</html>" in content.lower():
            return f"[OK] {file_path}"
        else:
            return f"[ERROR] {file_path}\nMissing <html> tags"
    except Exception as e:
        return f"[ERROR] {file_path}\n{str(e)}"


def validate_dockerfile(file_path):
    try:
        result = subprocess.run(["docker", "build", "--dry-run", "-f", file_path, "."], capture_output=True, text=True)
        if result.returncode == 0:
            return f"[OK] {file_path}"
        else:
            return f"[ERROR] {file_path}\n{result.stderr.strip()}"
    except FileNotFoundError:
        return f"[ERROR] {file_path}\nDocker not installed, skipped."


def validate_sql_file(file_path):
    try:
        with open(file_path, "r") as f:
            content = f.read()
        if ";" in content:  # Basic check
            return f"[OK] {file_path}"
        else:
            return f"[ERROR] {file_path}\nNo SQL statements found"
    except Exception as e:
        return f"[ERROR] {file_path}\n{str(e)}"


def validate_cpp_file(file_path):
    try:
        result = subprocess.run(["g++", "-fsyntax-only", file_path], capture_output=True, text=True)
        if result.returncode == 0:
            return f"[OK] {file_path}"
        else:
            return f"[ERROR] {file_path}\n{result.stderr.strip()}"
    except FileNotFoundError:
        return f"[ERROR] {file_path}\nG++ not installed, skipped."
