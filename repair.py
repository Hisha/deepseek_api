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
    """
    Attempt to repair invalid files by regenerating them using context + error info.
    """
    for attempt in range(1, MAX_REPAIR_ATTEMPTS + 1):
        logging.info(f"[Repair] Attempt {attempt}/{MAX_REPAIR_ATTEMPTS}")

        for file_info in failed_files:
            file_path = file_info["file"]
            issues = file_info["issues"]
            rel_path = os.path.relpath(file_path, project_folder)

            # ✅ Update UI before repairing
            update_job_status(
                job_id,
                "processing",
                message=f"Repairing file...",
                current_step=f"Attempt {attempt}/{MAX_REPAIR_ATTEMPTS}: {rel_path}"
            )

            repair_prompt = f"""
You are an expert software engineer.
Repair the file: {rel_path}

Project Description:
{original_prompt}

Full Plan:
{json.dumps(plan, indent=2)}

Current Issues:
{issues}

Rules:
- Rewrite the entire file content correctly.
- Fix all validation errors.
- Do NOT output markdown or commentary, only the code.
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
                raw_output = result.stdout.strip()
                cleaned_output = clean_code_output(raw_output)

                if not cleaned_output or len(cleaned_output.splitlines()) < 2:
                    cleaned_output = f"# ERROR: LLM returned insufficient repair content for {rel_path}\n"

                with open(file_path, "w") as f:
                    f.write(cleaned_output)

                logging.info(f"[Repair] Updated {rel_path}")
            except Exception as e:
                logging.error(f"[Repair] Error fixing {rel_path}: {e}")

        # ✅ Re-validate after each repair attempt
        validation_results = validate_project(project_folder)
        report_path = write_validation_report(project_folder, job_id, validation_results)
        failed_files = analyze_validation_results(validation_results)

        if not failed_files:
            logging.info("[Repair] All issues resolved!")
            update_job_status(job_id, "completed", f"Repaired successfully. Report: {report_path}")
            return True

    logging.warning("[Repair] Max repair attempts reached. Some files still have issues.")
    update_job_status(job_id, "completed", f"Partial success. See VALIDATION_REPORT.txt")
    return False
