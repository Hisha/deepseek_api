import os
import subprocess
import logging
import json
from db import update_job_status

# Paths
LLAMA_PATH = "/home/smithkt/llama.cpp/build/bin/llama-cli"
MODEL_CODE_PATH = "/home/smithkt/models/qwen/qwen2.5-coder-14b-instruct-q4_0.gguf"
PROJECTS_DIR = "/home/smithkt/deepseek_projects"

# Performance settings for quality
THREADS = "28"           # Max threads for your dual Xeon
CTX_SIZE = "8192"        # Large context window
N_PREDICT = "4096"       # Longer outputs for full code
TEMP = "0.25"            # Lower = more deterministic
TOP_P = "0.9"
REPEAT_PENALTY = "1.05"  # Slight penalty to avoid loops

def generate_files(job_id):
    """Generate all files listed in plan.json using Qwen2.5."""
    project_folder = os.path.join(PROJECTS_DIR, f"job_{job_id}")
    plan_path = os.path.join(project_folder, "plan.json")

    # Validate plan.json exists
    if not os.path.exists(plan_path):
        update_job_status(job_id, "error", "Missing plan.json")
        return False

    with open(plan_path, "r") as f:
        try:
            plan = json.load(f)
        except json.JSONDecodeError:
            update_job_status(job_id, "error", "Invalid plan.json")
            return False

    files = plan.get("files", [])
    if not files:
        update_job_status(job_id, "error", "No files in plan.json")
        return False

    total_files = len(files)
    logging.info(f"[Project Job {job_id}] Starting code generation for {total_files} files.")

    for idx, file_info in enumerate(files, start=1):
        rel_path = file_info.get("path")
        prompt = file_info.get("prompt")

        if not rel_path or not prompt:
            logging.warning(f"[Project Job {job_id}] Skipping file with missing path or prompt.")
            continue

        abs_path = os.path.join(project_folder, rel_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        # Log progress in server logs
        logging.info(f"[Project Job {job_id}] Generating file {idx}/{total_files}: {rel_path}")

        # Build llama.cpp command
        cmd = [
            LLAMA_PATH,
            "-m", MODEL_CODE_PATH,
            "-t", THREADS,
            "--ctx-size", CTX_SIZE,
            "--n-predict", N_PREDICT,
            "--temp", TEMP,
            "--top-p", TOP_P,
            "--repeat-penalty", REPEAT_PENALTY,
            "-p", f"Write the full content for the file: {rel_path}\n{prompt}\n"
        ]

        try:
            with open(abs_path, "w") as out_file:
                proc = subprocess.Popen(cmd, stdout=out_file, stderr=subprocess.PIPE, text=True)
                proc.wait()

            if proc.returncode != 0:
                stderr_output = proc.stderr.read()
                logging.error(f"[Project Job {job_id}] Error generating {rel_path}: {stderr_output}")
        except Exception as e:
            logging.error(f"[Project Job {job_id}] Exception while writing {rel_path}: {e}")

    update_job_status(job_id, "completed", f"All {total_files} files generated.")
    logging.info(f"[Project Job {job_id}] Code generation complete.")
    return True
