def analyze_validation_results(validation_results):
    """Return a list of files that failed with [ERROR] or critical warnings."""
    failed_files = []
    for file_path, result in validation_results.items():
        if "[ERROR]" in result:
            failed_files.append({
                "file": file_path,
                "issues": result
            })
    return failed_files
