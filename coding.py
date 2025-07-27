import os
import subprocess
import json
import logging
import re
from validation import validate_project, write_validation_report
from analyzer import analyze_validation_results
from repair import repair_project
from dependency_check import scan_missing_dependencies, log_dependency_fix_instructions

# ----------------------------
# Clean LLM Output
# ----------------------------
def clean_code_output(raw_output):
    raw_output = re.sub(r'^.*assistant\s*', '', raw_output, flags=re.DOTALL)
    raw_output = re.sub(r'>\s*EOF.*$', '', raw_output, flags=re.MULTILINE)
    raw_output = re.sub(r"^```[a-zA-Z]*", "", raw_output.strip(), flags=re.MULTILINE)
    raw_output = re.sub(r"```$", "", raw_output, flags=re.MULTILINE)
    return raw_output.strip()

# ----------------------------
# Fix Includes for C++
# ----------------------------
def fix_cpp_includes(project_folder):
    logging.info(f"[FixIncludes] Scanning for header files...")
    header_map = {}
    for root, _, files in os.walk(project_folder):
        for file in files:
            if file.endswith(".h"):
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, project_folder).replace("\\", "/")
                header_map[file] = rel_path

    include_pattern = re.compile(r'#include\s+"([^"]+)"')
    fixes_applied = 0
    for root, _, files in os.walk(project_folder):
        for file in files:
            if file.endswith(".cpp") or file.endswith(".h"):
                file_path = os.path.join(root, file)
                with open(file_path, "r") as f:
                    content = f.read()
                updated_content = content
                for match in include_pattern.findall(content):
                    if match in header_map:
                        correct_path = header_map[match]
                        updated_content = updated_content.replace(
                            f'#include "{match}"', f'#include "{correct_path}"'
                        )
                if updated_content != content:
                    with open(file_path, "w") as f:
                        f.write(updated_content)
                    logging.info(f"[FixIncludes] Updated includes in {file_path}")
                    fixes_applied += 1
    logging.info(f"[FixIncludes] Total include fixes applied: {fixes_applied}")
    return fixes_applied

# ----------------------------
# Auto-Fix Functions for Multi-Language
# ----------------------------
def autofix_dockerfile(project_folder, language="cpp"):
    docker_path = os.path.join(project_folder, "Dockerfile")
    base_image = {
        "cpp": "ubuntu:22.04",
        "python": "python:3.10-slim",
        "go": "golang:1.21",
        "java": "maven:3.9.4-eclipse-temurin-17"
    }.get(language, "ubuntu:22.04")

    if os.path.exists(docker_path):
        with open(docker_path, "r") as f:
            content = f.read()
    else:
        content = f"FROM {base_image}\nWORKDIR /app\n"

    if language == "cpp":
        if "RUN apt-get" not in content:
            content += "\nRUN apt-get update && apt-get install -y build-essential cmake libsqlite3-dev zlib1g-dev libboost-all-dev libsdl2-dev\n"
        if "RUN cmake" not in content:
            content += "\nRUN cmake . && make\n"
        if "CMD" not in content:
            content += '\nCMD ["./main"]\n'
    elif language == "python":
        if "COPY requirements.txt" not in content:
            content += "\nCOPY requirements.txt .\nRUN pip install -r requirements.txt\n"
        if "CMD" not in content:
            content += '\nCMD ["python3", "main.py"]\n'
    elif language == "go":
        if "RUN go build" not in content:
            content += "\nCOPY . .\nRUN go mod tidy && go build -o app\n"
        if "CMD" not in content:
            content += '\nCMD ["./app"]\n'
    elif language == "java":
        if "RUN mvn package" not in content:
            content += "\nCOPY . .\nRUN mvn package\n"
        if "CMD" not in content:
            content += '\nCMD ["java", "-jar", "target/app.jar"]\n'

    with open(docker_path, "w") as f:
        f.write(content)
    logging.info(f"[AutoFix] Updated Dockerfile for {language.upper()} project.")

# ----------------------------
# Detect Language
# ----------------------------
def detect_language(files):
    for f in files:
        if f["path"].endswith(".cpp"):
            return "cpp"
        elif f["path"].endswith(".py"):
            return "python"
        elif f["path"].endswith(".go"):
            return "go"
        elif f["path"].endswith(".java"):
            return "java"
    return "cpp"  # default

# ----------------------------
# Main Function
# ----------------------------
def generate_files(job_id, PROJECTS_DIR, LLAMA_PATH, MODEL_CODE_PATH, update_job_status):
    project_folder = os.path.join(PROJECTS_DIR, f"job_{job_id}")
    plan_path = os.path.join(project_folder, "plan.json")
    prompt_path = os.path.join(project_folder, "prompt.txt")

    if not os.path.exists(plan_path) or not os.path.exists(prompt_path):
        update_job_status(job_id, "error", "Missing plan.json or prompt.txt.")
        return False

    with open(plan_path) as f:
        plan = json.load(f)
    with open(prompt_path) as f:
        original_prompt = f.read().strip()

    files = plan.get("files", [])
    if not files:
        update_job_status(job_id, "error", "No files in plan.json.")
        return False

    language = detect_language(files)
    total_files = len(files)
    logging.info(f"[Job {job_id}] Detected language: {language.upper()}. Starting generation for {total_files} files...")

    # Generate Files
    for idx, file_info in enumerate(files, start=1):
        path = file_info.get("path")
        abs_path = os.path.join(project_folder, path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        context_prompt = f"""
Generate the COMPLETE file for: {path}
Project Description:
{original_prompt}
Full Plan:
{json.dumps(plan, indent=2)}
Rules:
- Output ONLY code (no markdown).
- Ensure all imports and paths are correct.
"""
        progress = int((idx / total_files) * 70)
        update_job_status(job_id, "processing", message=f"Generating file {idx}/{total_files}: {path}", progress=progress, current_step=f"File {idx}/{total_files} - {path}")

        cmd = [LLAMA_PATH, "-m", MODEL_CODE_PATH, "-t", "28", "--ctx-size", "8192", "--n-predict", "4096", "--temp", "0.25", "--top-p", "0.9", "--repeat-penalty", "1.05", "-p", context_prompt]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=1500)
            cleaned_output = clean_code_output(result.stdout.strip())
            with open(abs_path, "w") as f:
                f.write(cleaned_output or f"# ERROR: No content generated for {path}")
            logging.info(f"[Job {job_id}] ✅ File saved: {path}")
        except Exception as e:
            logging.error(f"[Job {job_id}] ❌ Error generating {path}: {e}")

    update_job_status(job_id, "processing", message="Applying auto-fixes...", progress=80)
    if language == "cpp":
        fix_cpp_includes(project_folder)
    autofix_dockerfile(project_folder, language)

    missing = scan_missing_dependencies(project_folder)
    if missing.get("missing"):
        log_dependency_fix_instructions(missing["missing"])

    update_job_status(job_id, "processing", message="Validating project...", progress=85)
    validation_results = validate_project(project_folder)
    report_path = write_validation_report(project_folder, job_id, validation_results)
    failed_files = analyze_validation_results(validation_results)

    if failed_files:
        update_job_status(job_id, "processing", message="Repairing files...", progress=90)
        repair_project(job_id, project_folder, failed_files, original_prompt, plan, LLAMA_PATH, MODEL_CODE_PATH, validate_project, analyze_validation_results, write_validation_report, update_job_status)

    update_job_status(job_id, "completed", f"Project complete. Report: {report_path}", 100, "Completed")
    return True
