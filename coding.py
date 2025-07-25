import os
import subprocess
import json
import logging
import re
from validation import validate_project, write_validation_report
from analyzer import analyze_validation_results
from repair import repair_project

def clean_code_output(raw_output):
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
        update_job_status(job_id, "error", "Missing plan.json or prompt.txt.")
        return False

    # ✅ Load plan
    with open(plan_path) as f:
        plan = json.load(f)

    # ✅ Load original prompt
    try:
        with open(prompt_path) as f:
            original_prompt = f.read().strip()
    except Exception as e:
        logging.error(f"[Job {job_id}] Could not read prompt.txt: {e}")
        update_job_status(job_id, "error", "Failed to read prompt.txt.")
        return False

    # ✅ Extract files
    files = plan.get("files", [])
    total_files = len(files)
    if total_files == 0:
        update_job_status(job_id, "error", "No files found in plan.json.")
        return False

    logging.info(f"[Job {job_id}] Starting file generation for {total_files} files...")

    # ✅ File Generation Phase
    for idx, file_info in enumerate(files, start=1):
        path = file_info.get("path")
        abs_path = os.path.join(project_folder, path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        # ✅ Context Prompt
        context_prompt = f"""
You are an expert software engineer. Generate the COMPLETE content for:
{path}

Project Description:
{original_prompt}

Full Project Plan:
{json.dumps(plan, indent=2)}

Rules:
- Output ONLY the code (no markdown, no extra text).
- Ensure imports and references match other files.
"""

        progress = int((idx / total_files) * 100)
        current_step = f"Generating file {idx}/{total_files}: {path}"
        update_job_status(job_id, "processing", current_step, progress)
        logging.info(f"[Job {job_id}] {current_step}")

        # ✅ Call LLM
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
            logging.error(f"[Job {job_id}] ❌ Error generating {path}: {e}")
            with open(abs_path, "w") as out_file:
                out_file.write(f"# ERROR: {e}")

    # ✅ All files generated
    logging.info(f"[Job {job_id}] ✅ Finished generating all {total_files} files.")
    update_job_status(job_id, "processing", f"Generated {total_files} files. Starting validation...")

    # ✅ Phase 2: Validation
    logging.info(f"[Job {job_id}] ➡ Starting validation phase...")
    update_job_status(job_id, "processing", "Validating generated project...")

    try:
        logging.info(f"[Job {job_id}] Calling validate_project()...")
        validation_results = validate_project(project_folder)
        logging.info(f"[Job {job_id}] Validation completed successfully.")
    except Exception as e:
        logging.error(f"[Job {job_id}] ❌ Error during validate_project(): {e}")
        update_job_status(job_id, "error", f"Validation failed: {e}")
        return False

    try:
        logging.info(f"[Job {job_id}] Writing validation report...")
        report_path = write_validation_report(project_folder, job_id, validation_results)
        logging.info(f"[Job {job_id}] Report written: {report_path}")
    except Exception as e:
        logging.error(f"[Job {job_id}] ❌ Error writing validation report: {e}")
        update_job_status(job_id, "error", f"Report writing failed: {e}")
        return False

    # ✅ Phase 3: Analyze & Repair
    logging.info(f"[Job {job_id}] ➡ Starting analysis and repair (if needed)...")
    failed_files = analyze_validation_results(validation_results)
    if failed_files:
        update_job_status(job_id, "processing", f"Repairing {len(failed_files)} files...")
        repair_project(
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
        )

    # ✅ Finalize
    logging.info(f"[Job {job_id}] ➡ Finalizing job and returning report...")
    update_job_status(job_id, "completed", f"Project generation complete. Report: {report_path}")
    logging.info(f"[Job {job_id}] ✅ Complete.")
    return True
