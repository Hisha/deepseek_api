import logging

def analyze_validation_results(validation_results):
    """
    Analyze validation results and return a structured list of files that need repairs.
    Includes:
    - Files with [ERROR]
    - Files with critical [WARN] issues (e.g., Dockerfile problems, invalid dependencies)
    Skips:
    - Cosmetic warnings (placeholders, tidy not installed)
    """
    failed_files = []

    CRITICAL_WARN_KEYWORDS = [
        "Missing FROM", "Missing CMD", "Missing build step",
        "Invalid packages", "sqlite3 not installed or failed"
    ]

    for file_path, result in validation_results.items():
        if "[ERROR]" in result:
            logging.info(f"[Analyzer] ❌ Critical error in {file_path}: {result}")
            failed_files.append({
                "file": file_path,
                "issues": result
            })
        elif "[WARN]" in result:
            if any(keyword in result for keyword in CRITICAL_WARN_KEYWORDS):
                logging.info(f"[Analyzer] ⚠ Critical warning in {file_path}: {result}")
                failed_files.append({
                    "file": file_path,
                    "issues": result
                })
            else:
                logging.info(f"[Analyzer] ℹ Ignoring non-critical warning for {file_path}: {result}")

    logging.info(f"[Analyzer] Found {len(failed_files)} files requiring repair.")
    return failed_files
