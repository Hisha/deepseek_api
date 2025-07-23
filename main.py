from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
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
from json import JSONDecodeError

try:
    from json_repair import repair_json  # Optional: pip install json-repair
except ImportError:
    repair_json = None  # Skip if not installed

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = FastAPI(root_path="/chat")
templates = Jinja2Templates(directory="templates")
templates.env.globals["now"] = datetime.now
eastern = pytz.timezone("US/Eastern")
PROJECTS_DIR = "/home/smithkt/deepseek_projects"
os.makedirs(PROJECTS_DIR, exist_ok=True)

# Initialize database
init_db()

LLAMA_PATH = "/home/smithkt/llama.cpp/build/bin/llama-cli"
MODEL_CODE_PATH = "/home/smithkt/models/deepseek/deepseek-coder-6.7b-instruct.Q4_K_M.gguf"
MODEL_PLAN_PATH = "/home/smithkt/models/mistral/mistral-7b-instruct-v0.2.Q4_K_M.gguf"

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

def get_autotune_settings(prompt):
    cpu_threads = os.cpu_count()
    available_ram_gb = psutil.virtual_memory().available / (1024**3)

    ctx_size = 4096
    n_predict = 1024
    batch_size = 512

    if available_ram_gb > 128:
        n_predict = 4096
        batch_size = 1024
    elif available_ram_gb > 64:
        n_predict = 3072
        batch_size = 768
    elif available_ram_gb > 32:
        n_predict = 2048
        batch_size = 512
    else:
        n_predict = 1024
        batch_size = 256

    if len(prompt) > 1000 and n_predict < 4096:
        n_predict = min(4096, n_predict + 512)

    return {
        "threads": str(cpu_threads),
        "ctx_size": str(ctx_size),
        "n_predict": str(n_predict),
        "batch_size": str(batch_size)
    }

#####################################################################################
#                                   GET                                             #
#####################################################################################

@app.get("/", response_class=HTMLResponse)
async def get_chat(request: Request):
    return templates.TemplateResponse("chat.html", {
        "request": request,
        "prompt": "",
        "output": ""
    })

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

@app.get("/status")
async def status():
    return JSONResponse({"status": "running", "worker": "active"})

#####################################################################################
#                                   POST                                            #
#####################################################################################

@app.post("/", response_class=HTMLResponse)
async def post_chat(request: Request, prompt: str = Form(...), generate_project: str = Form(None)):
    job_type = "project" if generate_project else "chat"
    job_id = add_job(prompt, job_type)
    message = f"Your {job_type} job has been queued. Job ID: {job_id}"
    return templates.TemplateResponse("chat.html", {
        "request": request,
        "prompt": "",
        "output": message
    })

#####################################################################################
#                                  Planner                                          #
#####################################################################################

def generate_plan(job_id, prompt):
    """Stage 1: Create a structured plan.json using Mistral planner model."""
    project_folder = os.path.join(PROJECTS_DIR, f"job_{job_id}")
    os.makedirs(project_folder, exist_ok=True)

    # Strict JSON prompt
    plan_prompt = f"""
You are a software project planner.

Task:
Based on this project description:
{prompt}

Respond ONLY with valid JSON. The JSON MUST:
- Have a key "project_name" (short string).
- Have a key "files" (array of objects).
- Each file object MUST have:
    - "path" (string)
    - "description" (string)
    - "prompt" (string)

Example:
{{
  "project_name": "sample project",
  "files": [
    {{
      "path": "main_file.ext",
      "description": "Main application entry point",
      "prompt": "Write the core logic based on the project requirements."
    }},
    {{
      "path": "ui/template.ext",
      "description": "User interface template",
      "prompt": "Create a responsive user interface using a standard UI framework."
    }},
    {{
      "path": "dependencies.txt",
      "description": "Dependencies list",
      "prompt": "List all required dependencies for the project."
    }}
  ]
}}

Rules:
- Output ONLY JSON, no explanations or comments.
- Start with '{{' and end with '}}'.
- If unsure, output: {{ "project_name": "", "files": [] }}
"""

    # Auto settings
    perf_settings = get_autotune_settings(plan_prompt)
    cmd = [
        LLAMA_PATH, "-m", MODEL_PLAN_PATH,
        "-t", perf_settings["threads"],
        "--ctx-size", perf_settings["ctx_size"],
        "--n-predict", perf_settings["n_predict"],
        "--batch-size", perf_settings["batch_size"],
        "--temp", "0.1",
        "--repeat-penalty", "1.1",
        "--top-p", "0.8",
        "-p", plan_prompt
    ]

    logging.info(f"[Project Job {job_id}] Generating structured plan.json...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    raw_output = result.stdout.strip()

    if not raw_output:
        logging.error(f"[Project Job {job_id}] Planner returned empty output.")
        update_job_status(job_id, "error", "Planner output empty or invalid.")
        return False

    # Extract JSON
    start = raw_output.find("{")
    end = raw_output.rfind("}")
    if start == -1 or end == -1:
        update_job_status(job_id, "error", "No valid JSON block found.")
        logging.error(f"[Project Job {job_id}] Raw output:\n{raw_output[:1000]}")
        return False

    json_text = raw_output[start:end+1]
    logging.info(f"[Project Job {job_id}] Raw JSON candidate:\n{json_text[:500]}")

    try:
        plan = json.loads(json_text)
    except JSONDecodeError as e:
        logging.error(f"[Project Job {job_id}] JSON decode error: {e}")
        if repair_json:
            try:
                plan = json.loads(repair_json(json_text))
            except Exception as e2:
                update_job_status(job_id, "error", f"Failed after repair: {e2}")
                return False
        else:
            update_job_status(job_id, "error", f"Invalid JSON: {e}")
            return False

    if "files" not in plan or not isinstance(plan["files"], list):
        update_job_status(job_id, "error", "Plan JSON missing 'files' key.")
        return False

    # Save plan.json
    plan_path = os.path.join(project_folder, "plan.json")
    with open(plan_path, "w") as f:
        json.dump(plan, f, indent=2)

    update_job_status(job_id, "planned", f"Plan generated with {len(plan['files'])} files.")
    logging.info(f"[Project Job {job_id}] Plan saved at {plan_path}")
    return True

#####################################################################################
#                                  Worker                                           #
#####################################################################################

def worker():
    logging.info("Worker thread started")
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
                    generate_plan(job_id, prompt)
                else:
                    update_job_status(job_id, "error", "Chat jobs not implemented yet.")
            else:
                time.sleep(3)
        except Exception as e:
            logging.error(f"Worker encountered an error: {e}")
            time.sleep(5)

Thread(target=worker, daemon=True).start()
