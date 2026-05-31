"""Lio — Flask entrypoint.

Run locally:
    export ANTHROPIC_API_KEY=sk-ant-...
    python lio_app.py

Default port: 5050 (Lumia owns 5000).
"""

import os
import traceback

from dotenv import load_dotenv
load_dotenv()  # picks up .env at repo root if present

from flask import Flask, render_template, request, jsonify

from lio.capabilities import outbound, content, market_intel, campaign, competitive, images, research
from lio.core import crm, mailer, imap_client, inbox_sync

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB upload cap

CAPABILITIES = {
    "outbound": outbound,
    "content": content,
    "market_intel": market_intel,
    "campaign": campaign,
    "competitive": competitive,
    "research": research,
}


@app.route("/")
def index():
    return render_template("lio.html")


@app.route("/api/run", methods=["POST"])
def api_run():
    data = request.get_json(silent=True) or {}
    cap_name = data.get("capability")
    payload = data.get("payload") or {}

    cap = CAPABILITIES.get(cap_name)
    if not cap:
        return jsonify({"ok": False, "error": f"unknown capability: {cap_name!r}"}), 400

    try:
        result = cap.run(payload)
        return jsonify({"ok": True, "result": result})
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/images", methods=["POST"])
def api_images():
    mode = (request.form.get("mode") or request.values.get("mode") or "").strip()
    prompt = (request.form.get("prompt") or "").strip()

    if mode not in ("generate", "edit"):
        return jsonify({"ok": False, "error": "mode must be 'generate' or 'edit'"}), 400
    if not prompt:
        return jsonify({"ok": False, "error": "prompt is required"}), 400

    try:
        if mode == "generate":
            result = images.run_generate(prompt)
        else:
            file = request.files.get("source")
            if not file:
                return jsonify({"ok": False, "error": "source image is required for edit mode"}), 400
            data = file.read()
            mime = file.mimetype or "image/png"
            result = images.run_edit(prompt, data, mime_type=mime, source_filename=file.filename)
        return jsonify({"ok": True, "result": result})
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/research", methods=["GET", "POST"])
def api_research():
    """Run the evidence-based research pipeline (Semantic Scholar → PDF → Claude).

    GET:  /lio/api/research?q=B2B+cold+email+response+rate
    POST: { "query": "...", "search_limit": 25, "pdf_limit": 8 }
    """
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        query = (data.get("query") or data.get("q") or "").strip()
        search_limit = int(data.get("search_limit") or 25)
        pdf_limit = int(data.get("pdf_limit") or 8)
    else:
        query = (request.args.get("q") or request.args.get("query") or "").strip()
        search_limit = int(request.args.get("search_limit") or 25)
        pdf_limit = int(request.args.get("pdf_limit") or 8)

    if not query:
        return jsonify({"ok": False, "error": "query is required (?q=... or POST body 'query')"}), 400

    try:
        result = research.run_research(query, search_limit=search_limit, pdf_limit=pdf_limit)
        return jsonify({"ok": True, "result": result})
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/crm/contacts")
def api_crm_list():
    contacts = crm.load_all()
    seg = (request.args.get("segment") or "").strip()
    status = (request.args.get("status") or "").strip()
    tier = (request.args.get("tier") or "").strip()
    q = (request.args.get("q") or "").strip().lower()

    def matches(c):
        if seg and c.get("segment") != seg: return False
        if status and c.get("status") != status: return False
        if tier and str(c.get("tier")) != tier: return False
        if q:
            blob = " ".join([
                c.get("name") or "", c.get("company") or "",
                c.get("title") or "", c.get("email") or "",
                " ".join(((c.get("personalization") or {}).get("hooks")) or []),
            ]).lower()
            if q not in blob: return False
        return True

    out = [c for c in contacts if matches(c)]
    summary = {
        "total": len(contacts),
        "shown": len(out),
        "valid_statuses": crm.VALID_STATUSES,
    }
    return jsonify({"ok": True, "contacts": out, "summary": summary})


@app.route("/api/crm/contact/<contact_id>")
def api_crm_get(contact_id):
    c = crm.get(contact_id)
    if not c:
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True, "contact": c})


@app.route("/api/crm/contact/<contact_id>", methods=["POST", "PATCH"])
def api_crm_update(contact_id):
    patch = request.get_json(silent=True) or {}
    try:
        c = crm.update(contact_id, patch)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    if not c:
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True, "contact": c})


@app.route("/api/mailer/status")
def api_mailer_status():
    return jsonify({"ok": True, "mailer": mailer.status(), "imap": imap_client.status()})


@app.route("/api/mailer/inbox/sync", methods=["POST"])
def api_inbox_sync():
    data = request.get_json(silent=True) or {}
    limit = int(data.get("limit") or 50)
    only_unseen = bool(data.get("only_unseen", False))
    try:
        result = inbox_sync.sync(limit=limit, only_unseen=only_unseen)
        return jsonify(result)
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/mailer/inbox/peek")
def api_inbox_peek():
    """Read recent inbox messages WITHOUT updating the CRM. Useful for an inbox view."""
    limit = int(request.args.get("limit") or 25)
    only_unseen = request.args.get("only_unseen", "false").lower() in ("1", "true", "yes")
    try:
        result = imap_client.fetch_recent(limit=limit, only_unseen=only_unseen)
        return jsonify(result)
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(exc)}), 500


def _is_hard_flag(flag: str) -> bool:
    """Hard flags block live-send. Soft flags are informational only."""
    s = (flag or "").lower()
    hard_patterns = [
        "verify", "email guessed", "email pattern guessed", "guessed email",
        "domain typo", "domain has typo", "verify domain",
        "bounce on", "bounce ", "fit risk", "different scope",
        "no public estimator", "out of icp", "out-of-icp",
        "ahmad personal", "do not queue", "do not email",
    ]
    return any(p in s for p in hard_patterns)


def _hard_flags(flags: list[str]) -> list[str]:
    return [f for f in (flags or []) if _is_hard_flag(f)]


@app.route("/api/crm/send/<contact_id>", methods=["POST"])
def api_crm_send(contact_id):
    payload = request.get_json(silent=True) or {}
    dry_run = bool(payload.get("dry_run"))

    contact = crm.get(contact_id)
    if not contact:
        return jsonify({"ok": False, "error": "contact not found"}), 404

    # Safety guardrails
    if (contact.get("status") or "").lower() == "active client":
        return jsonify({"ok": False, "error": "blocked: contact is an Active Client — cold send refused"}), 400
    blocking = _hard_flags(contact.get("needs_review_flags") or [])
    if blocking:
        return jsonify({
            "ok": False,
            "error": "blocked: contact has hard review flags that need resolving",
            "flags": blocking,
        }), 400
    to_email = (contact.get("email") or "").strip()
    if "@" not in to_email:
        return jsonify({"ok": False, "error": "blocked: contact has no valid email"}), 400
    draft_path = contact.get("draft_email_path")
    if not draft_path:
        return jsonify({"ok": False, "error": "no draft attached to this contact"}), 400

    abs_draft = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), draft_path))
    allowed_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lio", "data", "outreach_drafts")
    if not abs_draft.startswith(allowed_root + os.sep):
        return jsonify({"ok": False, "error": "draft path outside allowed root"}), 400
    if not os.path.exists(abs_draft):
        return jsonify({"ok": False, "error": f"draft file missing: {draft_path}"}), 400

    try:
        with open(abs_draft, "r", encoding="utf-8") as f:
            draft = __import__("json").load(f)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"failed to read draft: {exc}"}), 500

    subject = (payload.get("subject_override") or draft.get("subject") or "").strip()
    body = (payload.get("body_override") or draft.get("body") or "").strip()
    if not subject or not body:
        return jsonify({"ok": False, "error": "draft missing subject or body"}), 400

    result = mailer.send(
        to_email=to_email,
        to_name=contact.get("name") or "",
        subject=subject,
        body=body,
        contact_id=contact_id,
        dry_run=dry_run,
    )

    if result.get("ok") and not dry_run:
        from datetime import datetime as _dt
        crm.update(contact_id, {
            "status": "Contacted",
            "last_contacted": _dt.now().date().isoformat(),
            "touches_sent": int(contact.get("touches_sent") or 0) + 1,
        })

    return jsonify({"ok": result.get("ok", False), "result": result})


@app.route("/api/crm/draft/<path:relpath>")
def api_crm_draft(relpath):
    base = os.path.dirname(os.path.abspath(__file__))
    target = os.path.normpath(os.path.join(base, relpath))
    # Only allow paths inside lio/data/outreach_drafts/
    allowed_root = os.path.join(base, "lio", "data", "outreach_drafts")
    if not target.startswith(allowed_root + os.sep):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    if not os.path.exists(target):
        return jsonify({"ok": False, "error": "not found"}), 404
    try:
        with open(target, "r", encoding="utf-8") as f:
            return jsonify({"ok": True, "draft": __import__("json").load(f)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/health")
def health():
    contacts = crm.load_all()
    return jsonify({
        "ok": True,
        "agent": "lio",
        "capabilities": list(CAPABILITIES.keys()) + ["images", "crm", "mailer", "research"],
        "anthropic_key_set": bool(os.getenv("ANTHROPIC_API_KEY")),
        "gemini_key_set": bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
        "mailer": mailer.status(),
        "imap": imap_client.status(),
        "crm_contacts": len(contacts),
    })


if __name__ == "__main__":
    port = int(os.getenv("LIO_PORT", "5050"))
    print(f"\n  Lio Marketing Agent running at http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
