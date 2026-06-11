"""
Convert all PPTX files in TPX_Projects subdirectories to PDF using LibreOffice.
Skips files that already have a matching PDF.

Usage:
    python convert_pptx.py
    python convert_pptx.py --dir /path/to/other/folder
"""

import argparse
import os
import subprocess

DEFAULT_DIR = "TPX_Projects"


def _bar(done: int, total: int, width: int = 40) -> str:
    filled = int(width * done / total) if total else 0
    return f"[{'█' * filled}{'░' * (width - filled)}] {done}/{total}"


def convert(tpx_dir: str) -> None:
    if not os.path.isdir(tpx_dir):
        print(f"[ERROR] Folder not found: {tpx_dir}")
        return

    # Collect all PPTX files first so we know the total for the progress bar
    pptx_files = [
        (entry.name, entry.path, fname)
        for entry in sorted(os.scandir(tpx_dir), key=lambda e: e.name)
        if entry.is_dir()
        for fname in sorted(os.listdir(entry.path))
        if fname.lower().endswith(".pptx")
    ]

    if not pptx_files:
        print("No PPTX files found.")
        return

    total = len(pptx_files)
    converted = skipped = errors = 0

    for i, (project, project_path, fname) in enumerate(pptx_files, start=1):
        label = f"{project}/{fname}"
        pdf_path = os.path.join(project_path, os.path.splitext(fname)[0] + ".pdf")

        print(f"\r{_bar(i - 1, total)}  {label[:40]:<40}", end="", flush=True)

        if os.path.exists(pdf_path):
            skipped += 1
            continue

        pptx_path = os.path.join(project_path, fname)
        result = subprocess.run(
            ["libreoffice", "--headless", "--convert-to", "pdf",
             pptx_path, "--outdir", project_path],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            converted += 1
        else:
            errors += 1
            # Print error on its own line so it doesn't get overwritten
            print(f"\r[ERROR] {label}: {result.stderr.strip()}")

    print(f"\r{_bar(total, total)}  done{' ' * 40}")
    print(f"\n{total} PPTX(s) — {converted} converted, {skipped} skipped, {errors} error(s)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert PPTX files to PDF via LibreOffice.")
    parser.add_argument("--dir", default=DEFAULT_DIR, help=f"Root folder to scan (default: {DEFAULT_DIR})")
    args = parser.parse_args()
    convert(args.dir)
