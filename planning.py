import os
import json
import subprocess
import logging
import re

# ------------------------------
# Extract and Clean JSON Output
# ------------------------------
def extract_first_json(raw_output):
    """
    Cleans LLM output and extracts the first valid JSON object.
    """
    # Remove assistant/user markers and EOF signals
    cleaned = re.sub(r'^.*assistant\s*', '', raw_output, flags=re.DOTALL)
    cleaned = re.sub(r'>\s*EOF.*$', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^```[a-zA-Z]*", "", cleaned.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"```$", "", cleaned, flags=re.MULTILINE)

    # Extract the first JSON object
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if not match:
        raise ValueError("No valid JSON object found in LLM output.")
    return match.group(0)


def load_plan_from_raw(raw_output):
    """
    Extract JSON from raw LLM output and load it as a dictionary.
    """
    json_str = extract_first_json(raw_output)
    return json.loads(json_str)


# ------------------------------
# Generate Project Plan
# ------------------------------
def generate_plan(job_id, prompt, projects_dir, llama_path, model_plan_path, update_job_status):
    project_folder = os.path.join(projects_dir, f"job_{job_id}")
    os.makedirs(project_folder, exist_ok=True)

    # ✅ Save original prompt for later phases
    prompt_file = os.path.join(project_folder, "prompt.txt")
    with open(prompt_file, "w") as f:
        f.write(prompt)

    # ✅ Architect Prompt
    plan_prompt = f"""
You are a senior software architect. Based on this description:
{prompt}

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
- Always include:
  - One main entry point file
  - A dependency file (requirements.txt, CMakeLists.txt, or similar)
  - A README.md
- Organize code into modular folders:
  - For **C++ projects**:
    - Place headers in `include/` folder
    - Place source files in `src/` folder
    - Include a `CMakeLists.txt` at the root
    - Add `include_directories(include)` in CMakeLists.txt
  - For **Python projects**:
    - Use `app/` folder for main logic
    - Place routes, config, and DB modules logically
- For HTML UI, place templates under `templates/`
- Add Dockerfile if containerization is required
- Add SQL schema file if DB is required
- Avoid placeholders: use real example content
- Output ONLY JSON (no markdown, no commentary)
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
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        raw_output = result.stdout.strip()
    except subprocess.TimeoutExpired:
        logging.error(f"[Project Job {job_id}] LLM process timed out.")
        update_job_status(job_id, "error", "Plan generation timed out.")
        return False
    except Exception as e:
        logging.error(f"[Project Job {job_id}] Subprocess error: {e}")
        update_job_status(job_id, "error", f"Plan generation failed: {e}")
        return False

    # ✅ Save raw output for debugging
    raw_path = os.path.join(project_folder, "plan_raw.txt")
    with open(raw_path, "w") as f:
        f.write(raw_output)

    # ✅ Extract JSON safely
    try:
        plan = load_plan_from_raw(raw_output)
    except Exception as e:
        logging.error(f"[Project Job {job_id}] JSON decode error: {e}")
        update_job_status(job_id, "error", "Plan generation failed: Invalid JSON.")
        return False

    # ✅ Save parsed plan.json
    plan_path = os.path.join(project_folder, "plan.json")
    try:
        with open(plan_path, "w") as f:
            json.dump(plan, f, indent=2)
    except Exception as e:
        logging.error(f"[Project Job {job_id}] Failed to write plan.json: {e}")
        update_job_status(job_id, "error", "Failed to save plan.json.")
        return False

    # ✅ Update status
    update_job_status(job_id, "planned", f"Plan saved with {len(plan.get('files', []))} files.")
    logging.info(f"[Project Job {job_id}] Plan saved at {plan_path}")
    return True
