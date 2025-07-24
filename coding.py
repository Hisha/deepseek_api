import os
import subprocess
import json
import logging

def generate_files(job_id, PROJECTS_DIR, LLAMA_PATH, MODEL_CODE_PATH, update_job_status):
    project_folder = os.path.join(PROJECTS_DIR, f"job_{job_id}")
    plan_path = os.path.join(project_folder, "plan.json")

    if not os.path.exists(plan_path):
        update_job_status(job_id, "error", "Plan file missing.")
        return False

    with open(plan_path) as f:
        plan = json.load(f)

    files = plan.get("files", [])
    total_files = len(files)

    if total_files == 0:
        update_job_status(job_id, "error", "No files found in plan.json.")
        return False

    for idx, file_info in enumerate(files, start=1):
        path = file_info.get("path")
        prompt = file_info.get("prompt", "").strip()

        if not path or not prompt:
            logging.warning(f"[Job {job_id}] Skipping file {idx} due to missing path or prompt.")
            continue

        abs_path = os.path.join(project_folder, path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        progress = int((idx / total_files) * 100)
        current_step = f"Generating file {idx}/{total_files}: {path}"
        update_job_status(job_id, "processing", message=current_step, progress=progress, current_step=current_step)
        logging.info(f"[Job {job_id}] {current_step}")

        cmd = [
            LLAMA_PATH, "-m", MODEL_CODE_PATH,
            "-t", "28",                # Threads
            "--ctx-size", "8192",      # Context size for big models
            "--n-predict", "4096",     # Allow big completions
            "--temp", "0.2",           # Lower temp for deterministic code
            "--top-p", "0.9",
            "--repeat-penalty", "1.1",
            "-p", prompt
        ]

        try:
            with open(abs_path, "w") as out_file:
                proc = subprocess.Popen(cmd, stdout=out_file, stderr=subprocess.PIPE, text=True)
                proc.wait()
        except Exception as e:
            logging.error(f"[Job {job_id}] Error generating {path}: {e}")
            update_job_status(job_id, "error", f"Failed to generate {path}")
            return False

    update_job_status(job_id, "completed", f"All {total_files} files generated successfully.")
    logging.info(f"[Job {job_id}] ✅ All files generated successfully.")
    return True
