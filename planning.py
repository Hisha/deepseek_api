import subprocess
import os
import json
import logging
import sqlite3

# ----------------- Config -----------------
LLAMA_PATH = "/home/smithkt/llama.cpp/build/bin/llama-cli"
MODEL_PLAN_PATH = "/home/smithkt/models/qwen/qwen2.5-coder-14b-instruct-q4_0.gguf"
PROJECTS_DIR = "/home/smithkt/deepseek_projects"
os.makedirs(PROJECTS_DIR, exist_ok=True)

def extract_json_from_output(raw_output: str) -> str:
    """
    Extract JSON block from Qwen's output (between ```json and ```).
    If not found, attempt fallback by finding first '{' and last '}'.
    """
    if "```json" in raw_output:
        start = raw_output.find("```json") + len("```json")
        end = raw_output.find("```", start)
        if end != -1:
            return raw_output[start:end].strip()
    # Fallback: find first '{' and last '}'
    start = raw_output.find("{")
    end = raw_output.rfind("}")
    if start != -1 and end != -1:
        return raw_output[start:end+1].strip()
    return ""

def generate_plan(job_id, prompt, update_job_status):
    """
    Runs Qwen to generate a project plan and saves raw + cleaned JSON.
    """
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

    cmd = [
        LLAMA_PATH, "-m", MODEL_PLAN_PATH,
        "-t", "28",
        "--ctx-size", "8192",
        "--n-predict", "4096",
        "--temp", "0.2",
        "--top-p", "0.9",
        "--repeat-penalty", "1.1",
        "-p", plan_prompt
    ]

    logging.info(f"[Project Job {job_id}] Running Qwen for plan generation...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)  # Allow long runs
    raw_output = result.stdout.strip()

    # Save raw output
    raw_path = os.path.join(project_folder, "plan_raw.txt")
    with open(raw_path, "w") as f:
        f.write(raw_output)

    # Extract JSON
    json_block = extract_json_from_output(raw_output)
    if not json_block:
        logging.error(f"[Project Job {job_id}] No JSON found in output.")
        update_job_status(job_id, "error", "No valid JSON found in output.")
        return False

    # Validate JSON
    try:
        plan = json.loads(json_block)
    except json.JSONDecodeError as e:
        logging.error(f"[Project Job {job_id}] JSON decode error: {e}")
        update_job_status(job_id, "error", f"Invalid JSON in plan. Check plan_raw.txt.")
        return False

    if "files" not in plan or not isinstance(plan["files"], list):
        update_job_status(job_id, "error", "Plan JSON missing 'files' key.")
        return False

    # Save plan.json
    plan_path = os.path.join(project_folder, "plan.json")
    with open(plan_path, "w") as f:
        json.dump(plan, f, indent=2)

    update_job_status(job_id, "planned", f"Plan saved with {len(plan['files'])} files.")
    logging.info(f"[Project Job {job_id}] Plan saved at {plan_path}")
    return True
