import logging
import os

def analyze_validation_results(validation_results, plan=None, project_folder=None, original_prompt=None):
    """
    Analyze validation results and return a structured list of files that need repairs.
    Includes:
    - Files with [ERROR]
    - Files with critical [WARN] issues (Dockerfile, CMake, SQLite integration, invalid dependencies)
    - Missing files from plan.json
    Adds extra context for encryption/compression tasks if found in prompt.
    """

    failed_files = []

    # Keywords for critical warnings
    CRITICAL_WARN_KEYWORDS = [
        "Missing FROM", "Missing CMD", "Missing build step",
        "Invalid packages", "sqlite3 not installed or failed",
        "Missing include_directories", "Missing find_package(SQLite3 REQUIRED)"
    ]

    # Extra repair hints from the original prompt
    prompt_hints = []
    if original_prompt:
        if "encryption" in original_prompt.lower():
            prompt_hints.append("Encryption")
        if "compression" in original_prompt.lower():
            prompt_hints.append("Compression")
        if "sqlite" in original_prompt.lower():
            prompt_hints.append("SQLite DB Integration")

    # ✅ Check for errors and critical warnings
    for file_path, result in validation_results.items():
        if "[ERROR]" in result:
            logging.info(f"[Analyzer] ❌ Critical error in {file_path}: {result}")
            failed_files.append({
                "file": file_path,
                "issues": result,
                "extra": prompt_hints
            })
        elif "[WARN]" in result:
            if any(keyword in result for keyword in CRITICAL_WARN_KEYWORDS):
                logging.info(f"[Analyzer] ⚠ Critical warning in {file_path}: {result}")
                failed_files.append({
                    "file": file_path,
                    "issues": result,
                    "extra": prompt_hints
                })
            else:
                logging.info(f"[Analyzer] ℹ Ignoring non-critical warning for {file_path}: {result}")

    # ✅ Check for missing files based on plan.json
    if plan and project_folder:
        for file_info in plan.get("files", []):
            rel_path = file_info.get("path")
            abs_path = os.path.join(project_folder, rel_path)
            if not os.path.exists(abs_path):
                logging.warning(f"[Analyzer] ❌ Missing file detected: {rel_path}")
                failed_files.append({
                    "file": abs_path,
                    "issues": "[MISSING] File does not exist",
                    "prompt": file_info.get("prompt"),
                    "extra": prompt_hints
                })

    logging.info(f"[Analyzer] Found {len(failed_files)} files requiring repair or regeneration.")
    return failed_files
