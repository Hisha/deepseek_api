import os
import json
import subprocess
import logging

def generate_files(job_id, projects_dir, llama_path, model_code_path, update_job_status):
    project_folder = os.path.join(projects_dir, f"job_{job_id}")
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
        update_job_status(job_id, "processing", f"Generating file {idx}/{total_files}: {path}")
        logging.info(f"[Project Job {job_id}] Generating file {idx}/{total_files}: {path}")

        cmd = [
            llama_path, "-m", model_code_path,
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
    logging.info(f"[Project Job {job_id}] Completed file generation.")
    return True
