import os
import json
import subprocess
import logging
import re

def extract_json_block(text):
    """Extract JSON block from raw model output."""
    # 1. Check for fenced JSON
    fenced_match = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", text)
    if fenced_match:
        return fenced_match.group(1)

    # 2. Otherwise, extract the first JSON object
    brace_match = re.search(r"(\{[\s\S]*\})", text)
    if brace_match:
        return brace_match.group(1)

    return None

def generate_plan(job_id, prompt, projects_dir, llama_path, model_plan_path, update_job_status):
    project_folder = os.path.join(projects_dir, f"job_{job_id}")
    os.makedirs(project_folder, exist_ok=True)

    # Save original prompt for Phase 2 context
    with open(os.path.join(project_folder, "prompt.txt"), "w") as f:
        f.write(prompt)

    plan_prompt = f"""
You are a senior software architect. Based on this description: {prompt}

Generate ONLY valid JSON in this format:
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
- Must include at least:
  - One main entry point file
  - A dependency file (requirements.txt or similar)
  - A README.md
- Split code into logical modules: routes, config, utils, templates, static if relevant.
- No arbitrary file count limit—add only necessary files for a production-ready implementation.
- Use exact keys: "path", "description", "prompt".
- Output ONLY JSON (no markdown, no commentary).
"""

    cmd = [
        llama_path, "-m", model_plan_path,
        "-t", "28",
        "--ctx-size", "8192",
        "--n-predict", "4096",
        "--temp", "0.2",
        "--top-p", "0.9",
        "--repeat-penalty", "1.1",
        "-p", plan_prompt
    ]

    logging.info(f"[Project Job {job_id}] Generating structured plan.json...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    raw_output = result.stdout.strip()

    # Save raw output for debugging
    raw_path = os.path.join(project_folder, "plan_raw.txt")
    with open(raw_path, "w") as f:
        f.write(raw_output)

    # ✅ Extract only the JSON block
    json_block = extract_json_block(raw_output)
    if not json_block:
        logging.error(f"[Project Job {job_id}] No JSON block found in model output.")
        update_job_status(job_id, "error", "Could not extract JSON from plan output.")
        return False

    try:
        plan = json.loads(json_block)
    except json.JSONDecodeError as e:
        logging.error(f"[Project Job {job_id}] JSON decode error: {e}")
        update_job_status(job_id, "error", "Invalid JSON in plan.")
        return False

    # Save parsed plan
    plan_path = os.path.join(project_folder, "plan.json")
    with open(plan_path, "w") as f:
        json.dump(plan, f, indent=2)

    update_job_status(job_id, "planned", f"Plan saved with {len(plan['files'])} files.")
    logging.info(f"[Project Job {job_id}] Plan saved at {plan_path}")
    return True
