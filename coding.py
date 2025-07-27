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
# Fix Includes
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
# Auto-Fix Functions
# ----------------------------
def autofix_cmake(project_folder):
    cmake_path = os.path.join(project_folder, "CMakeLists.txt")
    if os.path.exists(cmake_path):
        with open(cmake_path, "r") as f:
            content = f.read()
        fixes = False
        if "include_directories" not in content:
            content += "\ninclude_directories(include)\n"
            fixes = True
        # Add common dependencies
        for pkg in ["SQLite3", "ZLIB", "Boost", "SDL2"]:
            if f"find_package({pkg}" not in content:
                content += f"\nfind_package({pkg} REQUIRED)\n"
                fixes = True
        if fixes:
            with open(cmake_path, "w") as f:
                f.write(content)
            logging.info("[AutoFix] Updated CMakeLists.txt with missing directives.")

def autofix_dockerfile(project_folder):
    docker_path = os.path.join(project_folder, "Dockerfile")
    if os.path.exists(docker_path):
        with open(docker_path, "r") as f:
            content = f.read()
        if "RUN apt-get" not in content:
            content += "\nRUN apt-get update && apt-get install -y libsqlite3-dev zlib1g-dev libboost-all-dev libsdl2-dev\n"
        if "RUN cmake" not in content:
            content += "\nRUN cmake . && make\n"
        if "CMD" not in content:
            content += '\nCMD ["./main"]\n'
        with open(docker_path, "w") as f:
            f.write(content)
        logging.info("[AutoFix] Updated Dockerfile with dependencies and build steps.")

def autofix_sqlite_includes(project_folder):
    schema_exists = any("schema.sql" in files for _, _, files in os.walk(project_folder))
    if schema_exists:
        for root, _, files in os.walk(project_folder):
            for file in files:
                if file.endswith(".cpp"):
                    file_path = os.path.join(root, file)
                    with open(file_path, "r") as f:
                        content = f.read()
                    if "sqlite3.h" not in content:
                        content = '#include <sqlite3.h>\n' + content
                        with open(file_path, "w") as f:
                            f.write(content)
                        logging.info(f"[AutoFix] Added sqlite3.h include in {file_path}")

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
        cmd = [
            LLAMA_PATH, "-m", MODEL_CODE_PATH, "-t", "28",
            "--ctx-size", "8192", "--n-predict", "4096",
            "--temp", "0.25", "--top-p", "0.9", "--repeat-penalty", "1.05",
            "-p", context_prompt
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=1500)
            cleaned_output = clean_code_output(result.stdout.strip())
            with open(abs_path, "w") as f:
                f.write(cleaned_output or f"# ERROR: No content generated for {path}")
            logging.info(f"[Job {job_id}] ✅ File saved: {path}")
        except Exception as e:
            logging.error(f"[Job {job_id}] ❌ Error generating {path}: {e}")

    # Post-gen Auto Fixes
    fix_cpp_includes(project_folder)
    autofix_cmake(project_folder)
    autofix_dockerfile(project_folder)
    autofix_sqlite_includes(project_folder)

    # Dependency Check
    missing = scan_missing_dependencies(project_folder)
    if missing:
        log_dependency_fix_instructions(missing)

    # Validation & Repair
    validation_results = validate_project(project_folder)
    report_path = write_validation_report(project_folder, job_id, validation_results)
    failed_files = analyze_validation_results(validation_results)
    if failed_files:
        repair_project(job_id, project_folder, failed_files, original_prompt, plan,
                       LLAMA_PATH, MODEL_CODE_PATH, validate_project, analyze_validation_results,
                       write_validation_report, update_job_status)

    update_job_status(job_id, "completed", f"Project complete. Report: {report_path}", 100, "Completed")
    return True
