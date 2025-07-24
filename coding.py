import os
import subprocess
import json
import logging
import re

def clean_code_output(raw_output):
    """Removes markdown fences and trims whitespace."""
    cleaned = re.sub(r"^```[a-zA-Z]*", "", raw_output.strip())
    cleaned = re.sub(r"```$", "", cleaned)
    return cleaned.strip()

def generate_files(job_id, PROJECTS_DIR, LLAMA_PATH, MODEL_CODE_PATH, update_job_status):
    project_folder = os.path.join(PROJECTS_DIR, f"job_{job_id}")
    plan_path = os.path.join(project_folder, "plan.json")
    prompt_path = os.path.join(project_folder, "prompt.txt")

    if not os.path.exists(plan_path) or not os.path.exists(prompt_path):
        update_job_status(job_id, "error", "Missing plan or original prompt.")
        return False

    with open(plan_path) as f:
        plan = json.load(f)
    with open(prompt_path) as f:
        original_prompt = f.read().strip()

    files = plan.get("files", [])
    total_files = len(files)

    if total_files == 0:
        update_job_status(job_id, "error", "No files found in plan.json.")
        return False

    for idx, file_info in enumerate(files, start=1):
        path = file_info.get("path")
        abs_path = os.path.join(project_folder, path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        # Context-aware generation
        context_prompt = f"""
You are an expert developer. Generate the COMPLETE content for {path}.

Project Description:
{original_prompt}

Full Plan:
{json.dumps(plan, indent=2)}

Rules:
- Provide ONLY code (no markdown, no extra text).
- Ensure imports and references match other files.
"""

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
            "-p", context_prompt
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
            cleaned_output = clean_code_output(result.stdout.strip())
            if not cleaned_output:
                cleaned_output = "# ERROR: Empty file generated"

            with open(abs_path, "w") as out_file:
                out_file.write(cleaned_output)

            logging.info(f"[Job {job_id}] File saved: {path}")
        except Exception as e:
            logging.error(f"[Job {job_id}] Error generating {path}: {e}")
            with open(abs_path, "w") as out_file:
                out_file.write(f"# ERROR: {e}")

    update_job_status(job_id, "completed", f"All {total_files} files generated.")
    return True
