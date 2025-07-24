import os
import subprocess
import logging
from db import update_job_status

LLAMA_PATH = "/home/smithkt/llama.cpp/build/bin/llama-cli"
MODEL_PLAN_PATH = "/home/smithkt/models/qwen/qwen2.5-coder-14b-instruct-q4_0.gguf"
PROJECTS_DIR = "/home/smithkt/deepseek_projects"

def get_autotune_settings():
    cpu_threads = os.cpu_count()
    ctx_size = 8192
    batch_size = 512
    return {
        "threads": str(cpu_threads),
        "ctx_size": str(ctx_size),
        "batch_size": str(batch_size)
    }

def generate_plan(job_id, prompt):
    project_folder = os.path.join(PROJECTS_DIR, f"job_{job_id}")
    os.makedirs(project_folder, exist_ok=True)

    plan_prompt = f"""
You are a software project planner. Based on this description: {prompt}

Generate ONLY valid JSON following this structure:
{{
  "project_name": "short descriptive name",
  "files": [
    {{
      "path": "relative/file/path.ext",
      "description": "purpose of this file",
      "prompt": "specific and actionable instruction for generating the file"
    }}
  ]
}}

Rules:
- Use the actual project description to decide file names and descriptions.
- Output at least:
  - One main entry point file.
  - A file for dependencies (requirements.txt or similar).
  - At least one documentation file (README.md).
  - Templates or static folders if relevant.
- Include 5–12 realistic files, not placeholders.
- Use exact keys: "path", "description", "prompt".
- Output ONLY JSON (no text outside JSON).
"""

    perf_settings = get_autotune_settings()
    cmd = [
        LLAMA_PATH, "-m", MODEL_PLAN_PATH,
        "-t", perf_settings["threads"],
        "--ctx-size", perf_settings["ctx_size"],
        "--n-predict", "4096",
        "--batch-size", perf_settings["batch_size"],
        "--temp", "0.2",
        "--top-p", "0.9",
        "--repeat-penalty", "1.1",
        "-p", plan_prompt
    ]

    logging.info(f"[Project Job {job_id}] Generating raw plan output...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    raw_output = result.stdout.strip()

    raw_path = os.path.join(project_folder, "plan_raw.txt")
    with open(raw_path, "w") as f:
        f.write(raw_output)

    update_job_status(job_id, "planned", f"Raw plan saved at plan_raw.txt")
    logging.info(f"[Project Job {job_id}] Raw plan saved at {raw_path}")
