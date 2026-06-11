import streamlit as st
import os
import json

import config as _config


def pick_folder_dialog() -> str | None:
    """Open a native OS folder-picker dialog using tkinter (works for local runs)."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()                      # hide the blank tkinter root window
        root.wm_attributes("-topmost", True) # bring the dialog in front of the browser
        folder = filedialog.askdirectory(title="Select bundle folder")
        root.destroy()
        return folder or None
    except Exception:
        return None

st.set_page_config(page_title="Project Description Agent", layout="wide")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Settings")

    # Folder picker — text input + Browse button that opens a native OS dialog
    st.subheader("Input folder")

    if "bundle_path" not in st.session_state:
        st.session_state.bundle_path = (
            "project_description_agent_synthetic_dataset/bundle_001_internal_kb_chatbot"
        )

    col_path, col_btn = st.columns([3, 1])
    with col_path:
        bundle = st.text_input(
            "Path to bundle folder",
            value=st.session_state.bundle_path,
            help="Absolute or relative path to a folder containing project documents (.md, .txt, .pdf)",
            label_visibility="collapsed",
        )
        st.session_state.bundle_path = bundle  # keep in sync when user edits manually
    with col_btn:
        if st.button("Browse", use_container_width=True):
            picked = pick_folder_dialog()
            if picked:
                st.session_state.bundle_path = picked
                st.rerun()

    # Live feedback: show what files are detected in the chosen folder
    if bundle:
        if os.path.isdir(bundle):
            detected = [
                f for f in os.listdir(bundle)
                if not f.startswith(".") and f != "facts_cache.json"
                and os.path.isfile(os.path.join(bundle, f))
            ]
            if detected:
                st.caption(f"{len(detected)} file(s) detected: {', '.join(detected[:4])}"
                           + (" ..." if len(detected) > 4 else ""))
            else:
                st.warning("Folder exists but contains no documents.")
        else:
            st.error("Folder not found.")

    st.divider()
    st.subheader("Parameters")

    MODEL_OPTIONS = {
        "claude-haiku-4-5-20251001": "Haiku 4.5 — fast, cheap",
        "claude-sonnet-4-6":         "Sonnet 4.6 — balanced",
        "claude-opus-4-7":           "Opus 4.7 — best quality",
    }
    model = st.selectbox(
        "Model",
        list(MODEL_OPTIONS.keys()),
        format_func=lambda k: MODEL_OPTIONS[k],
    )
    language = st.selectbox("Output language", ["auto", "polish", "english"])
    dev_mode = st.checkbox(
        "Dev mode",
        value=False,
        help="Use text extraction instead of Claude vision for PDFs — much cheaper during development.",
    )

    st.subheader("Clarifying questions")
    qa_mode = st.radio(
        "Mode",
        ["Ask me", "Auto-answer", "Skip"],
        help=(
            "Ask me — you answer each question in the UI.\n\n"
            "Auto-answer — all questions get a single generic reply you write below.\n\n"
            "Skip — no Q&A at all; the writer works only from the documents."
        ),
    )
    auto_answer_text = ""
    if qa_mode == "Auto-answer":
        auto_answer_text = st.text_area(
            "Generic answer",
            value="No specific preference — use your best judgment based on the source documents.",
            height=80,
            help="This text is sent as the answer to every clarifying question.",
        )

    st.subheader("Advanced")
    pdf_pages = st.number_input("PDF pages per chunk", min_value=1, max_value=20, value=3,
                                help="Smaller = more API calls but less risk of hitting token limits on dense PDFs.")
    pdf_overlap = st.number_input("PDF overlap pages", min_value=0, max_value=5, value=1,
                                  help="Pages carried over from the previous chunk to preserve cross-boundary context.")
    max_clarify = st.number_input("Max clarify rounds", min_value=0, max_value=10, value=3,
                                  help="How many follow-up Q&A rounds the agent can request before proceeding.")
    max_revisions = st.number_input("Max revision rounds", min_value=1, max_value=10, value=3,
                                    help="How many times the challenger can send the writer back for fixes.")

    st.divider()
    st.subheader("Similar projects index")

    if "tpx_dir" not in st.session_state:
        st.session_state.tpx_dir = "TPX_Projects"

    col_tpx, col_tpx_btn = st.columns([3, 1])
    with col_tpx:
        tpx_dir = st.text_input(
            "TPX_Projects folder",
            value=st.session_state.tpx_dir,
            label_visibility="collapsed",
        )
        st.session_state.tpx_dir = tpx_dir
    with col_tpx_btn:
        if st.button("Browse", key="browse_tpx", use_container_width=True):
            picked = pick_folder_dialog()
            if picked:
                st.session_state.tpx_dir = picked
                st.rerun()

    # Show live index status
    if os.path.isdir(tpx_dir):
        from similar_projects import index_status
        status = index_status(tpx_dir)
        st.caption(
            f"{status['indexed']} / {status['total_subdirs']} projects indexed"
            + (f" · {len(status['needs_conversion'])} PPTX(s) need conversion" if status["needs_conversion"] else "")
            + (f" · {len(status['unindexed'])} unindexed" if status["unindexed"] else "")
        )

        if status["needs_conversion"]:
            if st.button("Convert PPTXs to PDF", use_container_width=True):
                with st.status("Converting...", expanded=True):
                    from similar_projects import convert_new_pptx
                    converted = convert_new_pptx(tpx_dir, progress_cb=st.write)
                    st.write(f"Done — {len(converted)} file(s) converted.")
                st.rerun()

        if status["unindexed"]:
            if st.button("Build / update index", use_container_width=True):
                with st.status("Indexing projects...", expanded=True):
                    from similar_projects import build_index
                    n = build_index(tpx_dir, progress_cb=st.write)
                    st.write(f"Done — {n} project(s) added to index.")
                st.rerun()
    else:
        st.warning("Folder not found.")

    st.divider()
    if st.button("Reset", use_container_width=True):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

# Apply all sidebar parameters to the config module before any pipeline code runs.
# The pipeline reads these at call time (not import time), so overriding here is enough.
_config.MODEL = model
_config.LANGUAGE = language
_config.DEV_MODE = dev_mode
_config.PDF_PAGES_PER_CHUNK = pdf_pages
_config.PDF_OVERLAP_PAGES = pdf_overlap
_config.MAX_CLARIFY_ROUNDS = max_clarify
_config.MAX_REVISION_ROUNDS = max_revisions

# ── Session state ─────────────────────────────────────────────────────────────
# Streamlit reruns the entire script on every user interaction.
# st.session_state persists values across those reruns, acting as the pipeline's memory.
if "stage" not in st.session_state:
    st.session_state.update(
        stage="ready",
        bundle=None,
        docs=None,
        qa_pairs=[],
        pending_questions=[],
        qa_round=0,
        facts=None,
        artifacts=None,
        output_dir=None,
    )

s = st.session_state  # shorthand

st.title("Project Description Agent")

# ── Stage: ready ──────────────────────────────────────────────────────────────
if s.stage == "ready":
    st.info("Set the folder path and parameters in the sidebar, then click **Start**.")
    folder_ok = os.path.isdir(bundle) and bool(bundle)
    if st.button("Start", type="primary", use_container_width=True, disabled=not folder_ok):
        s.bundle = bundle  # lock the selected folder for the whole run
        s.qa_mode = qa_mode
        s.auto_answer_text = auto_answer_text
        s.stage = "analysing"
        st.rerun()

# ── Stage: analysing ──────────────────────────────────────────────────────────
# st.status() shows a live-updating box while long-running code executes.
# Each st.write() inside it appears immediately as Python reaches that line.
elif s.stage == "analysing":
    try:
        with st.status("Analysing documents...", expanded=True):
            from analysis_pass import load_bundle, run_analysis
            s.docs = load_bundle(s.bundle)
            st.write(f"Loaded {len(s.docs)} document(s)")
            s.analysis = run_analysis(s.bundle)
            questions = s.analysis.get("clarifying_questions", [])
            st.write(f"Found {len(questions)} clarifying question(s)")

            if s.qa_mode == "Skip":
                s.pending_questions = []
                st.write("Clarifying questions skipped.")
            elif s.qa_mode == "Auto-answer":
                s.qa_pairs = [
                    {
                        "topic": item.get("topic", "unknown"),
                        "question": item.get("question", str(item)),
                        "answer": s.auto_answer_text,
                    }
                    for item in questions
                ]
                s.pending_questions = []
                st.write(f"Auto-answered {len(questions)} question(s).")
            else:
                s.pending_questions = list(questions)
    except Exception as exc:
        st.error(str(exc))
        if st.button("Back"):
            s.stage = "ready"
            st.rerun()
    else:
        s.stage = "running" if s.qa_mode in ("Skip", "Auto-answer") else "qa"
        st.rerun()

# ── Stage: qa ─────────────────────────────────────────────────────────────────
elif s.stage == "qa":
    st.subheader("Clarifying Questions")

    if s.qa_pairs:
        with st.expander(f"{len(s.qa_pairs)} question(s) already answered"):
            for qa in s.qa_pairs:
                st.markdown(f"**Q:** {qa['question']}  \n**A:** {qa['answer']}")

    pending = s.pending_questions

    if not pending:
        # No pending questions — ask the model if it has enough information yet.
        # This runs automatically without user input.
        try:
            with st.status("Checking if enough information was collected...", expanded=False):
                import anthropic
                from clarifying_loop import build_sufficiency_prompt

                client = anthropic.Anthropic()
                content = build_sufficiency_prompt(s.docs, s.qa_pairs)
                resp = client.beta.messages.create(
                    model=_config.MODEL,
                    max_tokens=_config.MAX_TOKENS_CLARIFY,
                    betas=["prompt-caching-2024-07-31"],
                    messages=[{"role": "user", "content": content}],
                )
                raw = resp.content[0].text.strip()
                if raw.startswith("```"):
                    raw = raw.split("```", 2)[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                    raw = raw.rsplit("```", 1)[0].strip()
                decision = json.loads(raw)
        except Exception as exc:
            st.error(str(exc))
            if st.button("Back"):
                s.stage = "ready"
                st.rerun()
        else:
            if decision["sufficient"] or s.qa_round >= _config.MAX_CLARIFY_ROUNDS:
                s.stage = "running"
            else:
                follow_ups = decision.get("follow_up_questions", [])
                if follow_ups:
                    s.pending_questions = [
                        {"topic": "follow_up", "question": q} for q in follow_ups
                    ]
                    s.qa_round += 1
                else:
                    s.stage = "running"
            st.rerun()
    else:
        label = "Initial questions" if s.qa_round == 0 else f"Follow-up round {s.qa_round}"
        st.caption(label)

        # st.form groups inputs so Streamlit only reruns when the user clicks Submit,
        # not on every keystroke.
        with st.form("qa_form"):
            answers = {}
            for i, item in enumerate(pending):
                q = item.get("question", str(item))
                answers[i] = st.text_area(q, height=80, key=f"q_{s.qa_round}_{i}")

            if st.form_submit_button("Submit answers", type="primary"):
                for i, item in enumerate(pending):
                    s.qa_pairs.append({
                        "topic": item.get("topic", "unknown"),
                        "question": item.get("question", str(item)),
                        "answer": answers[i] or "No answer.",
                    })
                s.pending_questions = []
                st.rerun()

# ── Stage: running ────────────────────────────────────────────────────────────
elif s.stage == "running":
    try:
        with st.status("Running pipeline...", expanded=True):
            from extractor import run_extraction
            from writer import write_artifacts
            from challenger import check_and_revise
            from config import make_output_dir

            st.write("Extracting facts from documents...")
            extraction = run_extraction(s.bundle)
            s.facts = extraction["facts"]
            st.write(f"Done — {len(s.facts)} facts extracted")

            st.write("Writing Project Brief and Implementation PRD...")
            artifacts = write_artifacts(s.facts, s.qa_pairs)
            st.write("Done — artifacts written")

            st.write("Challenging claims against source facts...")
            artifacts = check_and_revise(s.facts, artifacts, s.qa_pairs)
            st.write("Done — claims verified")

            st.write("Saving output to disk...")
            out = make_output_dir(s.bundle)
            with open(os.path.join(out, "project_brief.md"), "w") as f:
                f.write(artifacts["project_brief"])
            with open(os.path.join(out, "implementation_prd.md"), "w") as f:
                f.write(artifacts["implementation_prd"])
            s.artifacts = artifacts
            s.output_dir = out
            st.write(f"Saved to {out}/")
    except Exception as exc:
        st.error(str(exc))
        if st.button("Back"):
            s.stage = "ready"
            st.rerun()
    else:
        s.stage = "done"
        st.rerun()

# ── Stage: done ───────────────────────────────────────────────────────────────
elif s.stage == "done":
    st.success(f"Complete — output saved to `{s.output_dir}/`")

    tab_brief, tab_prd, tab_facts, tab_similar = st.tabs(
        ["Project Brief", "Implementation PRD", "Extracted Facts", "Similar Projects"]
    )

    with tab_brief:
        st.markdown(s.artifacts["project_brief"])
        st.download_button(
            "Download",
            s.artifacts["project_brief"],
            "project_brief.md",
            "text/markdown",
        )

    with tab_prd:
        st.markdown(s.artifacts["implementation_prd"])
        st.download_button(
            "Download",
            s.artifacts["implementation_prd"],
            "implementation_prd.md",
            "text/markdown",
        )

    with tab_facts:
        st.caption(f"{len(s.facts)} facts total — showing first 50")
        for fact in s.facts[:50]:
            with st.expander(fact["fact"][:80]):
                st.markdown(f"**Source:** {fact['source']}")
                st.markdown(f"**Quote:** _{fact['quote']}_")
        if len(s.facts) > 50:
            st.caption(f"...and {len(s.facts) - 50} more not shown")

    with tab_similar:
        from similar_projects import index_status, find_similar

        tpx_dir = st.session_state.get("tpx_dir", "TPX_Projects")
        status = index_status(tpx_dir) if os.path.isdir(tpx_dir) else {"indexed": 0}

        if status["indexed"] == 0:
            st.info(
                "No projects indexed yet. Use the **Similar projects index** section "
                "in the sidebar to convert PPTXs and build the index."
            )
        else:
            st.caption(f"Searching across {status['indexed']} indexed project(s)")

            if st.button("Find similar projects", type="primary"):
                with st.spinner("Searching..."):
                    try:
                        result = find_similar(
                            s.artifacts["project_brief"],
                            tpx_dir=tpx_dir,
                            top_k=min(3, status["indexed"]),
                        )
                        st.session_state.similar_result = result
                    except Exception as exc:
                        st.error(str(exc))

            if "similar_result" in st.session_state:
                result = st.session_state.similar_result
                st.markdown(result["explanation"])
                st.divider()
                for match in result["matches"]:
                    with st.expander(f"{match['project_name']}  —  score: {match['score']}"):
                        st.markdown(match["summary"])
