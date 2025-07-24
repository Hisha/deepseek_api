import os
import json
import subprocess
import logging

def generate_plan(job_id, prompt, projects_dir, llama_path, model_plan_path, update_job_status):
    project_folder = os.path.join(projects_dir, f"job_{job_id}")
    os.makedirs(project_folder, exist_ok=True)

    # Save original prompt for Phase 2 context
    with open(os.path.join(project_folder, "prompt.txt"), "w") as f:
        f.write(prompt)

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

    # Save raw output
    raw_path = os.path.join(project_folder, "plan_raw.txt")
    with open(raw_path, "w") as f:
        f.write(raw_output)

    # Extract JSON between ```json and ```
    start = raw_output.find("```json")
    end = raw_output.find("```", start + 7)
    if start != -1 and end != -1:
        json_block = raw_output[start + 7:end].strip()
    else:
        json_block = raw_output

    try:
        plan = json.loads(json_block)
    except json.JSONDecodeError as e:
        logging.error(f"[Project Job {job_id}] JSON decode error: {e}")
        update_job_status(job_id, "error", "Invalid JSON in plan.")
        return False

    plan_path = os.path.join(project_folder, "plan.json")
    with open(plan_path, "w") as f:
        json.dump(plan, f, indent=2)

    update_job_status(job_id, "planned", f"Plan saved with {len(plan['files'])} files.")
    logging.info(f"[Project Job {job_id}] Plan saved at {plan_path}")
    return True
