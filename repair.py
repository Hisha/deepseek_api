import subprocess
import json
import logging
import os
import re

MAX_REPAIR_ATTEMPTS = 5

# Dependency-related keywords to skip in repair attempts
DEPENDENCY_ERRORS = [
    "sqlite3.h: No such file", "zlib.h: No such file",
    "boost/asio.hpp: No such file", "SDL2/SDL.h: No such file",
    "[WARN] Missing dependency", "Missing includes detected"
]

def clean_code_output(raw_output):
    """
    Cleans LLM output from any markdown or extra content.
    """
    raw_output = re.sub(r'^.*assistant\s*', '', raw_output, flags=re.DOTALL)
    raw_output = re.sub(r'>\s*EOF.*$', '', raw_output, flags=re.MULTILINE)
    raw_output = re.sub(r"^```[a-zA-Z]*", "", raw_output.strip(), flags=re.MULTILINE)
    raw_output = re.sub(r"```$", "", raw_output, flags=re.MULTILINE)
    return raw_output.strip()

def is_dependency_issue(issues):
    """
    Check if the issue is due to missing external dependencies (skip in repair).
    """
    return any(dep_err in issues for dep_err in DEPENDENCY_ERRORS)

def repair_project(job_id, project_folder, failed_files, original_prompt, plan,
                   LLAMA_PATH, MODEL_CODE_PATH, validate_project,
                   analyze_validation_results, write_validation_report,
                   update_job_status):
    total_failures = len(failed_files)
    logging.info(f"[Repair] Starting repair process for {total_failures} files.")

    for attempt in range(1, MAX_REPAIR_ATTEMPTS + 1):
        logging.info(f"[Repair] Attempt {attempt}/{MAX_REPAIR_ATTEMPTS}")

        for idx, file_info in enumerate(failed_files, start=1):
            file_path = file_info["file"]
            issues = file_info["issues"]
            rel_path = os.path.relpath(file_path, project_folder)

            # ✅ Skip dependency-related problems
            if is_dependency_issue(issues):
                logging.warning(f"[Repair] Skipping {rel_path} (Dependency issue: requires external library)")
                continue

            # ✅ Prepare repair prompt
            file_specific_prompt = f"Fix issues in {rel_path}. Problems: {issues}"
            repair_prompt = f"""
You are an expert C++ software engineer.
File: {rel_path}

Project Description:
{original_prompt}

Plan:
{json.dumps(plan, indent=2)}

Task:
{file_specific_prompt}

Rules:
- Output the COMPLETE corrected file content.
- Fix logic and compilation errors.
- Do NOT include markdown, comments about the task, or explanations.
"""

            # ✅ Status update
            progress = int(((idx / total_failures) * 100) / MAX_REPAIR_ATTEMPTS)
            current_step = f"Repair Attempt {attempt}/{MAX_REPAIR_ATTEMPTS} - File {idx}/{total_failures}: {rel_path}"
            update_job_status(job_id, "processing", message="Repairing files...", progress=progress, current_step=current_step)
            logging.info(f"[Repair] {current_step}")

            # ✅ Call LLM for repair
            cmd = [
                LLAMA_PATH, "-m", MODEL_CODE_PATH, "-t", "28",
                "--ctx-size", "8192", "--n-predict", "4096",
                "--temp", "0.25", "--top-p", "0.9", "--repeat-penalty", "1.05",
                "-p", repair_prompt
            ]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
                cleaned_output = clean_code_output(result.stdout.strip())

                if not cleaned_output or len(cleaned_output.splitlines()) < 2:
                    cleaned_output = f"// ERROR: LLM returned insufficient repair content for {rel_path}\n"

                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, "w") as f:
                    f.write(cleaned_output)

                logging.info(f"[Repair] ✅ Updated {rel_path}")
            except Exception as e:
                logging.error(f"[Repair] ❌ Error repairing {rel_path}: {e}")

        # ✅ Re-validate after each repair attempt
        logging.info(f"[Repair] ✅ Re-validating after attempt {attempt}...")
        validation_results = validate_project(project_folder)
        report_path = write_validation_report(project_folder, job_id, validation_results)
        failed_files = analyze_validation_results(validation_results)

        if not failed_files:
            logging.info("[Repair] ✅ All issues resolved!")
            update_job_status(job_id, "completed", f"Repaired successfully. Report: {report_path}", 100, "Repair complete")
            return True

    # ✅ After max attempts
    logging.warning("[Repair] ⚠ Max repair attempts reached. Some files still have issues.")
    update_job_status(job_id, "completed", f"Partial success. See VALIDATION_REPORT.txt", 100, "Repair incomplete")
    return False
