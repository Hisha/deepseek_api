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


def extract_first_json_block(text: str) -> str:
    start = text.find("{")
    if start == -1:
        return None
    brace_count = 0
    for i, char in enumerate(text[start:], start=start):
        if char == "{":
            brace_count += 1
        elif char == "}":
            brace_count -= 1
            if brace_count == 0:
                return text[start:i + 1]
    return None


def process_project_job(job_id, prompt):
    try:
        project_folder = os.path.join(PROJECTS_DIR, f"job_{job_id}")
        os.makedirs(project_folder, exist_ok=True)

        # STRONG JSON-ONLY PROMPT
        plan_prompt = f"""
You are a code generation assistant.
Task: Based on this project description, output ONLY JSON that defines the file structure and purpose.

Project: {prompt}

Your response MUST:
- Start immediately with '{{'
- End immediately with '}}'
- Follow this structure:
{{
  "files": [
    {{"path": "app.py", "description": "Flask entry point"}},
    {{"path": "templates/index.html", "description": "Main HTML template"}},
    {{"path": "requirements.txt", "description": "Dependencies list"}}
  ]
}}

Do NOT include any explanation, comments, or extra text.
Respond ONLY with valid JSON.
"""

        # Combine performance and generation settings
        perf_settings = get_autotune_settings(plan_prompt)  # From your autotune logic
        gen_settings = get_task_settings("plan")

        cmd = [
            LLAMA_PATH, "-m", MODEL_PATH,
            "-t", perf_settings["threads"],
            "--ctx-size", perf_settings["ctx_size"],
            "--n-predict", gen_settings["n_predict"],
            "--batch-size", perf_settings["batch_size"],
            "--temp", gen_settings["temp"],
            "--repeat-penalty", gen_settings["repeat_penalty"],
            "--top-p", gen_settings["top_p"],
            "-p", plan_prompt
        ]

        # Add stop tokens if defined
        if "stop" in gen_settings:
            for stop in gen_settings["stop"]:
                cmd.extend(["--stop", stop])

        logging.info(f"[Project Job {job_id}] Generating project plan...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        raw_output = result.stdout.strip()

        # Extract JSON block
        json_block = extract_first_json_block(raw_output)
        if not json_block:
            update_job_status(job_id, "error", "No valid JSON object found in output")
            logging.error(f"[Project Job {job_id}] Raw output:\n{raw_output[:1000]}")
            return

        # Attempt to parse JSON
        try:
            plan = json.loads(json_block)
        except JSONDecodeError as e:
            logging.error(f"[Project Job {job_id}] JSON decode error: {e}")
            logging.error(f"Broken JSON snippet: {json_block[:1000]}")

            if repair_json:
                try:
                    logging.info(f"[Project Job {job_id}] Attempting JSON repair...")
                    fixed_json = repair_json(json_block)
                    plan = json.loads(fixed_json)
                except Exception as repair_err:
                    update_job_status(job_id, "error", f"Invalid JSON after repair: {repair_err}")
                    return
            else:
                update_job_status(job_id, "error", f"Invalid JSON: {e}")
                return

        # Validate JSON structure
        if "files" not in plan or not isinstance(plan["files"], list):
            update_job_status(job_id, "error", "Invalid plan format (missing 'files' key)")
            logging.error(f"[Project Job {job_id}] Invalid plan structure: {plan}")
            return

        # Save plan.json
        plan_path = os.path.join(project_folder, "plan.json")
        with open(plan_path, "w") as f:
            json.dump(plan, f, indent=2)

        update_job_status(job_id, "done", f"Project plan created with {len(plan['files'])} files.")
        logging.info(f"[Project Job {job_id}] Plan saved: {plan_path}")

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
