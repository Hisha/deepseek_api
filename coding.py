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

    for idx, file_info in enumerate(files, start=1):
        path = file_info["path"]
        prompt = file_info["prompt"]
        abs_path = os.path.join(project_folder, path)

        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        progress = int((idx / total_files) * 100)
        current_step = f"Generating file {idx}/{total_files}: {path}"
        update_job_status(job_id, "processing", message=current_step, progress=progress, current_step=current_step)
        logging.info(f"[Job {job_id}] {current_step}")

        cmd = [
            LLAMA_PATH, "-m", MODEL_CODE_PATH,
            "-t", "28",
            "--ctx-size", "8192",
            "--n-predict", "4096",
            "--temp", "0.3",
            "--top-p", "0.9",
            "--repeat-penalty", "1.05",
            "-p", prompt
        ]

        with open(abs_path, "w") as out_file:
            proc = subprocess.Popen(cmd, stdout=out_file, stderr=subprocess.PIPE, text=True)
            proc.wait()

    update_job_status(job_id, "completed", f"All {total_files} files generated.")
    logging.info(f"[Job {job_id}] All files generated successfully.")
    return True
