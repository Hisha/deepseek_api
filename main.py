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
        return local_time.strftime("%b %d, %Y %I:%M %p %Z")  # e.g., Jul 23, 2025 11:20 AM EDT
    except Exception:
        return iso_str

templates.env.filters["localtime"] = format_local_time

def get_autotune_settings(prompt):
    cpu_threads = os.cpu_count()
    available_ram_gb = psutil.virtual_memory().available / (1024**3)

    # Base values
    ctx_size = 4096
    n_predict = 1024
    batch_size = 512

    # Adjust n_predict based on RAM
    if available_ram_gb > 128:  # Huge server
        n_predict = 4096
        batch_size = 1024
    elif available_ram_gb > 64:
        n_predict = 3072
        batch_size = 768
    elif available_ram_gb > 32:
        n_predict = 2048
        batch_size = 512
    else:  # Low memory
        n_predict = 1024
        batch_size = 256

    # For very long prompts, increase n_predict
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
    """Quick health check for worker"""
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
#                                  Other                                            #
#####################################################################################

def get_task_settings(task):
    presets = {
        "plan": {
            "temp": "0.1",
            "repeat_penalty": "1.1",
            "top_p": "0.8",
            "n_predict": "768",
            "stop": ["}\n", "\n\n"]
        },
        "file": {
            "temp": "0.2",
            "repeat_penalty": "1.05",
            "top_p": "0.9",
            "n_predict": "2048"
        },
        "doc": {
            "temp": "0.3",
            "repeat_penalty": "1.0",
            "top_p": "0.95",
            "n_predict": "1500"
        }
    }
    return presets.get(task, presets["plan"])


def process_project_job(job_id, prompt):
    try:
        project_folder = os.path.join(PROJECTS_DIR, f"job_{job_id}")
        os.makedirs(project_folder, exist_ok=True)

        #####################
        # Phase 1: Planning #
        #####################
        plan_prompt = f"""
You are a software project planner.

Task:
Based on this project description:
{prompt}

Produce a detailed project structure with:
- List of files and their paths
- Description of each file's purpose
- For each file, include a suggested prompt for generating its code

Output Format:
Project Plan:
Files:
1. path: app.py
   description: Flask entry point
   prompt: Create a Flask web app with basic routing, showing a homepage and handling file uploads.

2. path: templates/index.html
   description: HTML template for upload form
   prompt: Create a simple HTML template using Bootstrap with a form for file uploads.

End your response with:
"END OF PLAN"
"""

        perf = get_autotune_settings(plan_prompt)
        plan_cfg = get_task_settings("plan")

        plan_cmd = [
            LLAMA_PATH, "-m", MODEL_PLAN_PATH,
            "-t", perf["threads"],
            "--ctx-size", perf["ctx_size"],
            "--n-predict", plan_cfg["n_predict"],
            "--batch-size", perf["batch_size"],
            "--temp", plan_cfg["temp"],
            "--repeat-penalty", plan_cfg["repeat_penalty"],
            "--top-p", plan_cfg["top_p"],
            "-p", plan_prompt
        ]
        if "stop" in plan_cfg:
            for stop in plan_cfg["stop"]:
                plan_cmd.extend(["--stop", stop])

        logging.info(f"[Project Job {job_id}] Generating plan...")
        result = subprocess.run(plan_cmd, capture_output=True, text=True, timeout=600)
        raw_plan = result.stdout.strip()

        plan_path = os.path.join(project_folder, "plan.txt")
        with open(plan_path, "w") as f:
            f.write(raw_plan)

        if not raw_plan or "path:" not in raw_plan:
            update_job_status(job_id, "error", "Planner output empty or invalid")
            return

        ###########################
        # Phase 2: Code Generation #
        ###########################
        logging.info(f"[Project Job {job_id}] Parsing plan and generating code...")

        files = []
        current = {}
        for line in raw_plan.splitlines():
            line = line.strip()
            if line.startswith("path:"):
                if current:
                    files.append(current)
                current = {"path": line.replace("path:", "").strip()}
            elif line.startswith("prompt:") and current is not None:
                current["prompt"] = line.replace("prompt:", "").strip()
        if current:
            files.append(current)

        code_cfg = get_task_settings("file")

        for file in files:
            full_path = os.path.join(project_folder, file["path"])
            os.makedirs(os.path.dirname(full_path), exist_ok=True)

            code_prompt = f"Generate the full code for {file['path']} based on this description:\n{file['prompt']}"
            code_perf = get_autotune_settings(code_prompt)

            code_cmd = [
                LLAMA_PATH, "-m", MODEL_CODE_PATH,
                "-t", code_perf["threads"],
                "--ctx-size", code_perf["ctx_size"],
                "--n-predict", code_cfg["n_predict"],
                "--batch-size", code_perf["batch_size"],
                "--temp", code_cfg["temp"],
                "--repeat-penalty", code_cfg["repeat_penalty"],
                "--top-p", code_cfg["top_p"],
                "-p", code_prompt
            ]

            logging.info(f"[Project Job {job_id}] Generating {file['path']}...")
            result = subprocess.run(code_cmd, capture_output=True, text=True, timeout=600)
            output = result.stdout.strip()

            with open(full_path, "w") as f:
                f.write(output)

        update_job_status(job_id, "done", f"Project plan + {len(files)} files created.")
        logging.info(f"[Project Job {job_id}] All files generated.")

    except Exception as e:
        logging.error(f"[Project Job {job_id}] Error: {e}")
        update_job_status(job_id, "error", str(e))

def worker():
    logging.info("Worker thread started (Auto-Tune enabled)")
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

                if job_type == "chat":
                    process_chat_job(job_id, prompt)
                elif job_type == "project":
                    process_project_job(job_id, prompt)
            else:
                time.sleep(3)
        except Exception as e:
            logging.error(f"Worker encountered an error: {e}")
            time.sleep(5)

# Start the worker in a background thread
Thread(target=worker, daemon=True).start()
