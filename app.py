"""Flask UI for the prompt manager — Editor / Tester / History.

State lives entirely on disk under prompts/. Every page re-reads from the
PromptManager so changes are visible immediately without restart.
"""
import os
import sys
import threading
import webbrowser
from pathlib import Path
from flask import Flask, abort, flash, redirect, render_template, request, url_for
from dotenv import load_dotenv

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from prompt_manager import PromptManager, PromptTester

PROMPTS_DIR = ROOT / "prompts"
PORT = int(os.environ.get("PORT", 5005))

app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
app.secret_key = "prompt-manager-dev-key-not-for-production"


def pm() -> PromptManager:
    return PromptManager(PROMPTS_DIR)


def _resolve_selection() -> tuple[str | None, str | None]:
    """Pick (project, name) from query params, falling back to first available."""
    p = pm()
    projects = p.list_projects()
    if not projects:
        return None, None

    project = request.values.get("project") or projects[0]
    if project not in projects:
        project = projects[0]

    prompts = p.list_prompts(project)
    if not prompts:
        return project, None
    name = request.values.get("name") or prompts[0]
    if name not in prompts:
        name = prompts[0]
    return project, name


def _ctx_globals():
    p = pm()
    return {
        "projects": p.list_projects(),
        "prompts_by_project": {proj: p.list_prompts(proj) for proj in p.list_projects()},
    }


@app.context_processor
def inject_globals():
    return _ctx_globals()


# ===== Editor tab =====
@app.route("/", methods=["GET"])
def editor():
    project, name = _resolve_selection()
    if not project or not name:
        return render_template("editor.html", project=None, name=None, record=None, active_tab="editor")
    record = pm().load(project, name)
    return render_template(
        "editor.html",
        project=project, name=name, record=record, active_tab="editor",
    )


@app.route("/save", methods=["POST"])
def save_version():
    project = request.form["project"]
    name = request.form["name"]
    prompt = request.form.get("prompt", "").strip()
    note = request.form.get("note", "").strip()
    if not prompt:
        flash("Prompt nie może być pusty.", "error")
        return redirect(url_for("editor", project=project, name=name))

    new_version = pm().save_new_version(project, name, prompt=prompt, note=note)
    flash(f"Zapisano jako wersja v{new_version} i ustawiono jako aktywną.", "success")
    return redirect(url_for("editor", project=project, name=name))


# ===== Tester tab =====
@app.route("/tester", methods=["GET", "POST"])
def tester():
    project, name = _resolve_selection()
    if not project or not name:
        return render_template("tester.html", project=None, name=None, record=None,
                               result=None, test_input="", active_tab="tester")

    record = pm().load(project, name)
    result = None
    test_input = request.form.get("test_input", "")

    if request.method == "POST" and request.form.get("action") == "run":
        if not test_input.strip():
            flash("Wklej input testowy zanim odpalisz test.", "error")
        elif "ANTHROPIC_API_KEY" not in os.environ:
            flash("Brakuje ANTHROPIC_API_KEY w .env.", "error")
        else:
            try:
                tester_ = PromptTester()
                result = tester_.test(
                    prompt=record.active_prompt,
                    test_input=test_input,
                    validation_schema=record.validation_schema,
                )
                # Persist test outcome onto the active version so the History tab shows it.
                pm().update_test_outcome(
                    project, name, record.current_version,
                    test_passed=result.is_valid,
                    test_input=test_input,
                    test_output=result.parsed_output,
                )
                record = pm().load(project, name)
            except Exception as e:
                flash(f"Test failed: {type(e).__name__}: {e}", "error")

    return render_template(
        "tester.html",
        project=project, name=name, record=record,
        result=result, test_input=test_input, active_tab="tester",
    )


# ===== History tab =====
@app.route("/history", methods=["GET"])
def history():
    project, name = _resolve_selection()
    if not project or not name:
        return render_template("history.html", project=None, name=None, record=None, active_tab="history")
    record = pm().load(project, name)
    return render_template(
        "history.html",
        project=project, name=name, record=record, active_tab="history",
    )


@app.route("/activate", methods=["POST"])
def activate():
    project = request.form["project"]
    name = request.form["name"]
    version = int(request.form["version"])
    pm().activate_version(project, name, version)
    flash(f"Aktywowano wersję v{version} promptu {project}/{name}.", "success")
    return redirect(url_for("history", project=project, name=name))


def _open_browser():
    webbrowser.open(f"http://127.0.0.1:{PORT}")


if __name__ == "__main__":
    if "ANTHROPIC_API_KEY" not in os.environ:
        print("WARN: ANTHROPIC_API_KEY not set — Tester tab will be disabled.")
    threading.Timer(1.0, _open_browser).start()
    app.run(host="127.0.0.1", port=PORT, debug=False)
