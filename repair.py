import subprocess
import json
import logging
import os
import re

MAX_REPAIR_ATTEMPTS = 5
DEPENDENCY_ERRORS = [
    "sqlite3.h: No such file", "zlib.h: No such file",
    "boost/asio.hpp: No such file", "SDL2/SDL.h: No such file"
]

def clean_code_output(raw_output):
    raw_output = re.sub(r'^.*assistant\s*', '', raw_output, flags=re.DOTALL)
    raw_output = re.sub(r'>\s*EOF.*$', '', raw_output, flags=re.MULTILINE)
    raw_output = re.sub(r"^```[a-zA-Z]*", "", raw_output.strip(), flags=re.MULTILINE)
    raw_output = re.sub(r"```$", "", raw_output, flags=re.MULTILINE)
    return raw_output.strip()

def repair_project(job_id, project_folder, failed_files, original_prompt, plan,
                   LLAMA_PATH, MODEL_CODE_PATH, validate_project,
                   analyze_validation_results, write_validation_report,
                   update_job_status):
    total_failures = len(failed_files)

    for attempt in range(1, MAX_REPAIR_ATTEMPTS + 1):
        logging.info(f"[Repair] Attempt {attempt}/{MAX_REPAIR_ATTEMPTS} - {total_failures} files")

        for idx, file_info in enumerate(failed_files, start=1):
            file_path = file_info["file"]
            issues = file_info["issues"]

            # Skip if dependency issue
            if any(dep_err in issues for dep_err in DEPENDENCY_ERRORS):
                logging.warning(f"[Repair] Skipping {file_path} (dependency issue)")
                continue

            rel_path = os.path.relpath(file_path, project_folder)
            file_specific_prompt = f"Fix issues in {rel_path}. Problems: {issues}"
            repair_prompt = f"""
You are an expert C++ engineer.
File: {rel_path}
Project:
{original_prompt}
Plan:
{json.dumps(plan, indent=2)}
Task:
{file_specific_prompt}
Rules:
- Output COMPLETE code only, no markdown.
- Fix logic and compilation errors.
"""
            cmd = [
                LLAMA_PATH, "-m", MODEL_CODE_PATH, "-t", "28",
                "--ctx-size", "8192", "--n-predict", "4096",
                "--temp", "0.25", "--top-p", "0.9", "--repeat-penalty", "1.05",
                "-p", repair_prompt
            ]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
                cleaned_output = clean_code_output(result.stdout.strip())
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, "w") as f:
                    f.write(cleaned_output or "# ERROR: Empty repair output")
                logging.info(f"[Repair] ✅ Updated {rel_path}")
            except Exception as e:
                logging.error(f"[Repair] ❌ Error fixing {rel_path}: {e}")

        validation_results = validate_project(project_folder)
        report_path = write_validation_report(project_folder, job_id, validation_results)
        failed_files = analyze_validation_results(validation_results)
        if not failed_files:
            update_job_status(job_id, "completed", f"All issues fixed. Report: {report_path}", 100, "Repair complete")
            return True

    logging.warning("[Repair] Max attempts reached. Some files still broken.")
    update_job_status(job_id, "completed", f"Partial success. See VALIDATION_REPORT.txt", 100, "Repair incomplete")
    return False
