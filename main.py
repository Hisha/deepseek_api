from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from threading import Thread
from datetime import datetime
import sqlite3
import logging
import pytz
import os
import time
import shutil
from dateutil import parser
from db import add_job, init_db, get_all_jobs, get_job, update_job_status
import planning
import coding
import quickmode  # ✅ Quick mode handler

# ----------------- Config -----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = FastAPI(root_path="/chat")
templates = Jinja2Templates(directory="templates")
templates.env.globals["now"] = datetime.now

eastern = pytz.timezone("US/Eastern")

# ✅ Centralized constants
PROJECTS_DIR = "/home/smithkt/deepseek_projects"
LLAMA_PATH = "/home/smithkt/llama.cpp/build/bin/llama-cli"
MODEL_PLAN_PATH = "/home/smithkt/models/qwen/qwen2.5-coder-14b-instruct-q4_0.gguf"
MODEL_CODE_PATH = "/home/smithkt/models/qwen/qwen2.5-coder-14b-instruct-q4_0.gguf"

os.makedirs(PROJECTS_DIR, exist_ok=True)
init_db()

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

# ----------------- Worker -----------------
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
                logging.info(f"[Worker] Processing job {job_id} ({job_type})")

                if job_type == "project":
                    update_job_status(job_id, "processing", "Generating plan...")
                    success = planning.generate_plan(
                        job_id, prompt, PROJECTS_DIR, LLAMA_PATH, MODEL_PLAN_PATH, update_job_status
                    )

                    if success:
                        update_job_status(job_id, "processing", "Generating code files...")
                        coding.generate_files(
                            job_id, PROJECTS_DIR, LLAMA_PATH, MODEL_CODE_PATH, update_job_status
                        )

                        # ✅ Create ZIP of the project
                        project_folder = os.path.join(PROJECTS_DIR, f"job_{job_id}")
                        zip_path = os.path.join(project_folder, f"job_{job_id}.zip")
                        shutil.make_archive(zip_path.replace(".zip", ""), 'zip', project_folder)
                        update_job_status(job_id, "completed", "Project generation complete.")
                        logging.info(f"[Worker] Job {job_id} zipped at {zip_path}")
                    else:
                        update_job_status(job_id, "error", "Plan generation failed.")

                elif job_type == "chat":
                    quickmode.generate_quick_code(job_id, prompt, LLAMA_PATH, MODEL_CODE_PATH, update_job_status)

            else:
                time.sleep(3)
        except Exception as e:
            logging.error(f"Worker error: {e}")
            time.sleep(5)

Thread(target=worker, daemon=True).start()

# ----------------- Routes -----------------
@app.get("/", response_class=HTMLResponse)
async def get_chat(request: Request):
    return templates.TemplateResponse("chat.html", {"request": request, "prompt": "", "output": ""})

@app.post("/", response_class=HTMLResponse)
async def post_chat(request: Request, prompt: str = Form(...), generate_project: str = Form(None)):
    job_type = "project" if generate_project else "chat"
    job_id = add_job(prompt, job_type)
    message = f"Your {job_type} job has been queued. Job ID: {job_id}"
    return templates.TemplateResponse("chat.html", {"request": request, "prompt": "", "output": message})

@app.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request):
    jobs = get_all_jobs()
    return templates.TemplateResponse("jobs.html", {"request": request, "jobs": jobs})

@app.get("/jobs/table", response_class=HTMLResponse)
async def jobs_table_partial(request: Request):
    jobs = get_all_jobs()
    return templates.TemplateResponse("partials/job_table.html", {"request": request, "jobs": jobs})

@app.get("/job/{job_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_id: int):
    job = get_job(job_id)
    return templates.TemplateResponse("partials/job_detail.html", {"request": request, "job": job})

@app.get("/job/{job_id}/download")
async def download_zip(job_id: int):
    project_folder = os.path.join(PROJECTS_DIR, f"job_{job_id}")
    zip_path = os.path.join(project_folder, f"job_{job_id}.zip")
    if os.path.exists(zip_path):
        return FileResponse(zip_path, media_type="application/zip", filename=f"job_{job_id}.zip")
    return HTMLResponse("<h1>ZIP file not found</h1>", status_code=404)
