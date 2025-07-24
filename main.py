from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from db import add_job, init_db, get_all_jobs, get_job, update_job_status
from threading import Thread
from datetime import datetime
import subprocess
import time
import sqlite3
import logging
import pytz
import os
import psutil
from dateutil import parser
import json
import zipfile
import shutil

# ----------------- Config -----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = FastAPI(root_path="/chat")
templates = Jinja2Templates(directory="templates")
templates.env.globals["now"] = datetime.now
eastern = pytz.timezone("US/Eastern")
PROJECTS_DIR = "/home/smithkt/deepseek_projects"
os.makedirs(PROJECTS_DIR, exist_ok=True)

init_db()

LLAMA_PATH = "/home/smithkt/llama.cpp/build/bin/llama-cli"
MODEL_QWEN_PATH = "/home/smithkt/models/qwen/qwen2.5-coder-14b-instruct-q4_0.gguf"

# ----------------- Helpers -----------------
def format_local_time(iso_str):
    if not iso_str:
        return "—"
    try:
        utc_time = parser.isoparse(iso_str)
        local_time = utc_time.astimezone(eastern)
        return local_time.strftime("%b %d, %Y %I:%M %p %Z")
    except Exception:
        return iso_str

templates.env.filters["localtime"] = format_local_time

def get_autotune_settings():
    cpu_threads = min(28, os.cpu_count())  # Use 28 threads max
    ctx_size = 8192
    batch_size = 512
    return {
        "threads": str(cpu_threads),
        "ctx_size": str(ctx_size),
        "batch_size": str(batch_size)
    }

def extract_after_inst(text: str) -> str:
    start = text.find("[/INST]")
    if start == -1:
        return text
    return text[start + len("[/INST]"):].strip()

# ----------------- Phase 1: Plan Generation -----------------
def generate_plan(job_id, prompt):
    project_folder = os.path.join(PROJECTS_DIR, f"job_{job_id}")
    os.makedirs(project_folder, exist_ok=True)

    plan_prompt = f"""
You are a senior software architect. Based on this description: {prompt}

Generate ONLY valid JSON with this structure:
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
- Use real filenames and directories relevant to the description.
- Output 5–12 meaningful files (entry point, templates, static assets, tests, docs, config).
- Include README.md and a dependencies file.
- NO placeholders like main_file.ext.
- Output ONLY JSON, no comments or extra text.
"""

    perf = get_autotune_settings()
    cmd = [
        LLAMA_PATH, "-m", MODEL_QWEN_PATH,
        "-t", perf["threads"],
        "--ctx-size", perf["ctx_size"],
        "--n-predict", "4096",
        "--batch-size", perf["batch_size"],
        "--temp", "0.2",
        "--top-p", "0.9",
        "--repeat-penalty", "1.1",
        "-p", plan_prompt
    ]

    logging.info(f"[Project Job {job_id}] Generating plan.json...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    raw_output = result.stdout.strip()

    # Extract after [/INST]
    json_block = extract_after_inst(raw_output)

    # Validate JSON
    try:
        plan = json.loads(json_block)
    except json.JSONDecodeError as e:
        logging.error(f"[Project Job {job_id}] JSON decode error: {e}")
        update_job_status(job_id, "error", "Invalid JSON in plan.")
        return False

    if "files" not in plan or not isinstance(plan["files"], list):
        update_job_status(job_id, "error", "Plan JSON missing 'files'.")
        return False

    # Save
    with open(os.path.join(project_folder, "plan.json"), "w") as f:
        json.dump(plan, f, indent=2)

    update_job_status(job_id, "planned", f"Plan created with {len(plan['files'])} files.")
    return True

# ----------------- Phase 2: File Generation -----------------
def generate_files(job_id):
    project_folder = os.path.join(PROJECTS_DIR, f"job_{job_id}")
    plan_path = os.path.join(project_folder, "plan.json")

    if not os.path.exists(plan_path):
        update_job_status(job_id, "error", "Plan missing.")
        return False

    with open(plan_path) as f:
        plan = json.load(f)

    files = plan["files"]
    for idx, file_info in enumerate(files, start=1):
        path = file_info["path"]
        file_prompt = file_info["prompt"]
        abs_path = os.path.join(project_folder, path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        attempt = 0
        success = False
        while attempt < 3 and not success:
            update_job_status(job_id, "processing", f"Generating {path} (Attempt {attempt+1})")
            logging.info(f"[Job {job_id}] Generating {path}...")

            cmd = [
                LLAMA_PATH, "-m", MODEL_QWEN_PATH,
                "-t", "28",
                "--ctx-size", "8192",
                "--n-predict", "4096",
                "--temp", "0.3",
                "--top-p", "0.9",
                "--repeat-penalty", "1.05",
                "-p", f"Generate ONLY the complete code for this file:\n{path}\n\nInstructions:\n{file_prompt}\n\nOutput ONLY code. No explanations."
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            raw_code = extract_after_inst(result.stdout.strip())

            if raw_code and len(raw_code.splitlines()) > 3:
                with open(abs_path, "w") as f:
                    f.write(raw_code)
                success = True
            else:
                attempt += 1

        if not success:
            logging.error(f"[Job {job_id}] Failed to generate {path} after retries.")

    # Zip the project
    zip_path = os.path.join(project_folder, "project.zip")
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for root, dirs, files_in_dir in os.walk(project_folder):
            for file in files_in_dir:
                if file != "project.zip":
                    full_path = os.path.join(root, file)
                    arc_name = os.path.relpath(full_path, project_folder)
                    zipf.write(full_path, arc_name)

    update_job_status(job_id, "completed", f"Project ready. Download: project.zip")
    return True

# ----------------- Worker -----------------
def worker():
    logging.info("Worker started")
    while True:
        try:
            conn = sqlite3.connect("jobs.db")
            c = conn.cursor()
            c.execute("SELECT id, prompt, type FROM jobs WHERE status = 'queued' ORDER BY id ASC LIMIT 1")
            job = c.fetchone()
            conn.close()

            if job:
                job_id, prompt, job_type = job
                update_job_status(job_id, "processing")

                if job_type == "project":
                    if generate_plan(job_id, prompt):
                        generate_files(job_id)
                else:
                    update_job_status(job_id, "error", "Chat handler not implemented")
            else:
                time.sleep(3)
        except Exception as e:
            logging.error(f"Worker error: {e}")
            time.sleep(5)

Thread(target=worker, daemon=True).start()

# ----------------- Routes -----------------
@app.get("/", response_class=HTMLResponse)
async def get_chat(request: Request):
    return templates.TemplateResponse("chat.html", {"request": request})

@app.post("/", response_class=HTMLResponse)
async def post_chat(request: Request, prompt: str = Form(...), generate_project: str = Form(None)):
    job_type = "project" if generate_project else "chat"
    job_id = add_job(prompt, job_type)
    return templates.TemplateResponse("chat.html", {"request": request, "output": f"Job {job_id} queued"})

@app.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request):
    jobs = get_all_jobs()
    return templates.TemplateResponse("jobs.html", {"request": request, "jobs": jobs})

@app.get("/jobs/table", response_class=HTMLResponse)
async def jobs_table(request: Request):
    jobs = get_all_jobs()
    return templates.TemplateResponse("partials/job_table.html", {"request": request, "jobs": jobs})

@app.get("/job/{job_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_id: int):
    job = get_job(job_id)
    return templates.TemplateResponse("partials/job_detail.html", {"request": request, "job": job})

@app.get("/download/{job_id}")
async def download_project(job_id: int):
    zip_path = os.path.join(PROJECTS_DIR, f"job_{job_id}/project.zip")
    if os.path.exists(zip_path):
        return FileResponse(zip_path, filename=f"project_{job_id}.zip")
    return JSONResponse({"error": "File not found"}, status_code=404)
