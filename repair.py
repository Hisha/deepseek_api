import subprocess
import json
import logging
import os
import re

MAX_REPAIR_ATTEMPTS = 5

def clean_code_output(raw_output):
    raw_output = re.sub(r'^.*assistant\s*', '', raw_output, flags=re.DOTALL)
    raw_output = re.sub(r'>\s*EOF.*$', '', raw_output, flags=re.MULTILINE)
    raw_output = re.sub(r"^```[a-zA-Z]*", "", raw_output.strip(), flags=re.MULTILINE)
    raw_output = re.sub(r"```$", "", raw_output, flags=re.MULTILINE)
    return raw_output.strip()

def repair_project(
    job_id,
    project_folder,
    failed_files,
    original_prompt,
    plan,
    LLAMA_PATH,
    MODEL_CODE_PATH,
    validate_project,
    analyze_validation_results,
    write_validation_report,
    update_job_status
):
    total_failures = len(failed_files)

    for attempt in range(1, MAX_REPAIR_ATTEMPTS + 1):
        logging.info(f"[Repair] Attempt {attempt}/{MAX_REPAIR_ATTEMPTS} - {total_failures} files to fix")

        for idx, file_info in enumerate(failed_files, start=1):
            file_path = file_info["file"]
            issues = file_info["issues"]
            rel_path = os.path.relpath(file_path, project_folder)
            is_missing = "[MISSING]" in issues

            extra_rule = ""
            if "requirements.txt" in rel_path:
                extra_rule = "- Remove invalid dependencies (sqlite3, os, sys, etc.). Only include external packages."
            if rel_path.lower() == "dockerfile":
                extra_rule += "\n- Ensure Dockerfile has FROM, build steps, and CMD."
            if rel_path.lower() == "cmakelists.txt":
                extra_rule += "\n- Ensure include_directories and find_package(SQLite3 REQUIRED) are present."
            if "SQLite" in issues:
                extra_rule += "\n- Ensure C++ code integrates SQLite with sqlite3.h and proper linking."
            if "compression" in original_prompt.lower() or "encryption" in original_prompt.lower():
                extra_rule += "\n- Implement basic compression and AES encryption utilities."

            progress = int(((idx / total_failures) * 100) / MAX_REPAIR_ATTEMPTS)
            current_step = f"Repair Attempt {attempt}/{MAX_REPAIR_ATTEMPTS} - File {idx}/{total_failures}: {rel_path}"
            update_job_status(job_id, "processing", message="Repairing files...", progress=progress, current_step=current_step)
            logging.info(f"[Repair] {current_step}")

            file_specific_prompt = f"Fix issues in {rel_path}. Current problems: {issues}"
            if is_missing:
                file_specific_prompt = f"Recreate missing file: {rel_path}."

            repair_prompt = f"""
You are an expert C++/software engineer.
File: {rel_path}

Project Description:
{original_prompt}

Plan:
{json.dumps(plan, indent=2)}

Task:
{file_specific_prompt}

Rules:
- Output COMPLETE file content.
- Fix all logic and validation issues.
- Do NOT output markdown or commentary, only the code.
{extra_rule}
"""

            cmd = [
                LLAMA_PATH, "-m", MODEL_CODE_PATH,
                "-t", "28",
                "--ctx-size", "8192",
                "--n-predict", "4096",
                "--temp", "0.25",
                "--top-p", "0.9",
                "--repeat-penalty", "1.05",
                "-p", repair_prompt
            ]

            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
                cleaned_output = clean_code_output(result.stdout.strip())
                if not cleaned_output or len(cleaned_output.splitlines()) < 2:
                    cleaned_output = f"# ERROR: LLM returned insufficient content for {rel_path}\n"

                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, "w") as f:
                    f.write(cleaned_output)
                logging.info(f"[Repair] ✅ Updated/Created {rel_path}")
            except Exception as e:
                logging.error(f"[Repair] ❌ Error fixing {rel_path}: {e}")

        logging.info(f"[Repair] ✅ Re-validating after attempt {attempt}...")
        validation_results = validate_project(project_folder)
        report_path = write_validation_report(project_folder, job_id, validation_results)
        failed_files = analyze_validation_results(validation_results)

        if not failed_files:
            logging.info("[Repair] ✅ All issues resolved!")
            update_job_status(job_id, "completed", f"Repaired successfully. Report: {report_path}", 100, "Repair complete")
            return True

    logging.warning("[Repair] ⚠ Max repair attempts reached. Some files still have issues.")
    update_job_status(job_id, "completed", f"Partial success. See VALIDATION_REPORT.txt", 100, "Repair incomplete")
    return False
