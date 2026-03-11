from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from functools import wraps
import json
from datetime import datetime, timedelta
import random

app = Flask(__name__)
app.secret_key = "equiswap_secret_2026"

# ─── MOCK DATABASE ─────────────────────────────────────────────────────────────
USERS = {
    "alex@equiswap.com": {
        "id": "u001", "name": "Alex Kim", "email": "alex@equiswap.com",
        "password": "demo123", "role": "specialist", "skills": ["TypeScript", "React", "Node.js"],
        "avatar": "AK", "trust_score": 94, "joined": "Jan 2026",
        "bio": "Full-stack engineer with 7 years experience. Ex-Google, YC alumni."
    },
    "maya@novamind.ai": {
        "id": "u002", "name": "Maya Patel", "email": "maya@novamind.ai",
        "password": "demo123", "role": "founder", "skills": [],
        "avatar": "MP", "trust_score": 88, "joined": "Nov 2025",
        "bio": "Founder of NovaMind AI. Building the future of enterprise LLMs."
    }
}

PROJECTS = [
    {"id": "p001", "name": "NovaMind AI", "category": "AI / ML", "equity_min": 1.5, "equity_max": 3.0,
     "skills": ["ML Engineer", "Python", "LLM"], "stage": "Seed", "match": 94, "logo": "NM",
     "color": "#006F87", "hot": True, "founder": "Maya Patel", "location": "San Francisco, CA",
     "raised": "$1.2M", "description": "Building enterprise-grade LLM fine-tuning infrastructure.",
     "vesting": "2yr vesting, 1yr cliff", "applicants": 12},
    {"id": "p002", "name": "GreenLedger", "category": "FinTech", "equity_min": 0.8, "equity_max": 2.0,
     "skills": ["Solidity", "React", "UX Design"], "stage": "Pre-Seed", "match": 87, "logo": "GL",
     "color": "#7E9C76", "hot": False, "founder": "James Okafor", "location": "Austin, TX",
     "raised": "$340K", "description": "Carbon credit tokenization on Ethereum.",
     "vesting": "4yr vesting, 1yr cliff", "applicants": 6},
    {"id": "p003", "name": "Meridian Health", "category": "HealthTech", "equity_min": 2.0, "equity_max": 4.0,
     "skills": ["iOS Dev", "HIPAA", "Product"], "stage": "Series A", "match": 79, "logo": "MH",
     "color": "#9B6B9B", "hot": False, "founder": "Dr. Sarah Lin", "location": "Boston, MA",
     "raised": "$4.2M", "description": "AI-powered remote patient monitoring platform.",
     "vesting": "3yr vesting, 6mo cliff", "applicants": 21},
    {"id": "p004", "name": "FlowCommerce", "category": "eCommerce", "equity_min": 0.5, "equity_max": 1.5,
     "skills": ["Shopify", "Growth", "Data Analyst"], "stage": "Pre-Seed", "match": 91, "logo": "FC",
     "color": "#D97706", "hot": True, "founder": "Lena Schmidt", "location": "Remote",
     "raised": "$180K", "description": "Headless commerce for D2C brands.",
     "vesting": "2yr vesting, no cliff", "applicants": 9},
    {"id": "p005", "name": "Orbit Analytics", "category": "SaaS", "equity_min": 1.0, "equity_max": 2.5,
     "skills": ["Go", "DevOps", "Product Strategy"], "stage": "Seed", "match": 83, "logo": "OA",
     "color": "#006F87", "hot": False, "founder": "Raj Mehta", "location": "New York, NY",
     "raised": "$780K", "description": "Real-time product analytics for B2B SaaS teams.",
     "vesting": "4yr vesting, 1yr cliff", "applicants": 14},
    {"id": "p006", "name": "VaultLegal AI", "category": "LegalTech", "equity_min": 1.2, "equity_max": 2.8,
     "skills": ["AI/NLP", "Node.js", "Legal Tech"], "stage": "Pre-Seed", "match": 88, "logo": "VL",
     "color": "#5a7a52", "hot": False, "founder": "Chen Wei", "location": "Chicago, IL",
     "raised": "$260K", "description": "AI contract review and equity agreement generation.",
     "vesting": "3yr vesting, 1yr cliff", "applicants": 5},
]

EQUITY_HOLDINGS = [
    {"company": "NovaMind AI", "percent": 2.5, "value": 48000, "vested_pct": 50,
     "stage": "Seed", "color": "#006F87", "logo": "NM", "start": "Feb 12, 2026"},
    {"company": "GreenLedger", "percent": 0.8, "value": 12400, "vested_pct": 25,
     "stage": "Pre-Seed", "color": "#7E9C76", "logo": "GL", "start": "Jan 5, 2026"},
]

PROPOSALS = [
    {"id": "pr001", "project": "NovaMind AI", "role": "ML Engineer", "equity": "2.5%",
     "status": "active", "stage": "Terms", "date": "Mar 1, 2026", "logo": "NM", "color": "#006F87"},
    {"id": "pr002", "project": "FlowCommerce", "role": "Growth Lead", "equity": "0.8%",
     "status": "awaiting", "stage": "Video Call", "date": "Mar 5, 2026", "logo": "FC", "color": "#D97706"},
    {"id": "pr003", "project": "Orbit Analytics", "role": "DevOps Engineer", "equity": "1.2%",
     "status": "awaiting", "stage": "Discovery", "date": "Mar 7, 2026", "logo": "OA", "color": "#006F87"},
    {"id": "pr004", "project": "GreenLedger", "role": "React Dev", "equity": "0.9%",
     "status": "completed", "stage": "Legal Sign-off", "date": "Feb 20, 2026", "logo": "GL", "color": "#7E9C76"},
]

MESSAGES = [
    {"id": "m001", "from": "Maya Patel", "from_co": "NovaMind AI", "avatar": "MP",
     "text": "Hey, are you available for the DocuSign call tomorrow at 3pm PST?",
     "time": "2m ago", "unread": True, "color": "#006F87"},
    {"id": "m002", "from": "James Okafor", "from_co": "GreenLedger", "avatar": "JO",
     "text": "The equity terms doc is ready for your review. Check Legal Vault.",
     "time": "1h ago", "unread": True, "color": "#7E9C76"},
    {"id": "m003", "from": "EquiSwap Team", "from_co": "EquiSwap", "avatar": "ES",
     "text": "Your Trust Score increased to 94! You're in the top 6% of specialists 🎉",
     "time": "3h ago", "unread": False, "color": "#006F87"},
    {"id": "m004", "from": "Lena Schmidt", "from_co": "FlowCommerce", "avatar": "LS",
     "text": "Loved your application. Can we schedule a 30-min intro call this week?",
     "time": "1d ago", "unread": False, "color": "#D97706"},
]

MILESTONES = [
    {"label": "Product MVP Design", "due": "Mar 15, 2026", "done": True, "project": "NovaMind AI"},
    {"label": "Backend API Integration", "due": "Apr 1, 2026", "done": True, "project": "NovaMind AI"},
    {"label": "Beta Launch (50 users)", "due": "Apr 20, 2026", "done": False, "project": "NovaMind AI"},
    {"label": "First 100 Active Users", "due": "May 10, 2026", "done": False, "project": "NovaMind AI"},
]

LEGAL_DOCS = [
    {"id": "d001", "name": "NovaMind AI — Equity Agreement", "type": "Equity Agreement",
     "status": "signed", "date": "Feb 14, 2026", "size": "2.4 MB"},
    {"id": "d002", "name": "GreenLedger — Term Sheet", "type": "Term Sheet",
     "status": "pending", "date": "Mar 6, 2026", "size": "1.1 MB"},
    {"id": "d003", "name": "NovaMind AI — SAFE Note", "type": "SAFE",
     "status": "signed", "date": "Feb 12, 2026", "size": "890 KB"},
]

# ─── AUTH DECORATOR ────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_email" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def get_current_user():
    return USERS.get(session.get("user_email"))

# ═══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    if "user_email" in session:
        return redirect(url_for("dashboard"))
    return render_template("landing.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").lower()
        password = request.form.get("password", "")
        user = USERS.get(email)
        if user and user["password"] == password:
            session["user_email"] = email
            return redirect(url_for("dashboard"))
        flash("Invalid email or password. Try: alex@equiswap.com / demo123", "error")
    return render_template("auth.html", mode="login")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("name", "")
        email = request.form.get("email", "").lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "specialist")
        if email in USERS:
            flash("Email already registered. Sign in instead.", "error")
            return render_template("auth.html", mode="signup")
        initials = "".join([w[0].upper() for w in name.split()[:2]])
        USERS[email] = {
            "id": f"u{len(USERS)+1:03d}", "name": name, "email": email,
            "password": password, "role": role, "skills": [],
            "avatar": initials or "?", "trust_score": 72, "joined": "Mar 2026", "bio": ""
        }
        session["user_email"] = email
        return redirect(url_for("dashboard"))
    return render_template("auth.html", mode="signup")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/dashboard")
@login_required
def dashboard():
    user = get_current_user()
    stats = {
        "proposals": len(PROPOSALS),
        "awaiting": len([p for p in PROPOSALS if p["status"] == "awaiting"]),
        "equity_pct": sum(h["percent"] for h in EQUITY_HOLDINGS),
        "equity_value": sum(h["value"] for h in EQUITY_HOLDINGS),
        "trust_score": user["trust_score"],
    }
    top_projects = sorted(PROJECTS, key=lambda x: x["match"], reverse=True)[:4]
    return render_template("dashboard.html", user=user, stats=stats,
                           projects=top_projects, proposals=PROPOSALS[:3],
                           messages=MESSAGES[:3])

@app.route("/marketplace")
@login_required
def marketplace():
    user = get_current_user()
    category = request.args.get("category", "All")
    filtered = PROJECTS if category == "All" else [p for p in PROJECTS if p["category"] == category]
    categories = ["All"] + list(dict.fromkeys(p["category"] for p in PROJECTS))
    return render_template("marketplace.html", user=user, projects=filtered,
                           categories=categories, active_cat=category)

@app.route("/project/<project_id>")
@login_required
def project_detail(project_id):
    user = get_current_user()
    project = next((p for p in PROJECTS if p["id"] == project_id), None)
    if not project:
        return redirect(url_for("marketplace"))
    return render_template("project_detail.html", user=user, project=project)

@app.route("/equity")
@login_required
def equity():
    user = get_current_user()
    total_value = sum(h["value"] for h in EQUITY_HOLDINGS)
    total_pct = sum(h["percent"] for h in EQUITY_HOLDINGS)
    return render_template("equity.html", user=user, holdings=EQUITY_HOLDINGS,
                           total_value=total_value, total_pct=total_pct)

@app.route("/dealflow")
@login_required
def dealflow():
    user = get_current_user()
    active_proposal = PROPOSALS[0]
    return render_template("dealflow.html", user=user, proposal=active_proposal,
                           milestones=MILESTONES, steps=[
                               {"id":1,"label":"Discovery","icon":"search","done":True},
                               {"id":2,"label":"Video Call","icon":"video","done":True},
                               {"id":3,"label":"Terms","icon":"file-text","active":True},
                               {"id":4,"label":"Legal Sign-off","icon":"shield","done":False},
                               {"id":5,"label":"Milestones","icon":"bar-chart-2","done":False},
                           ])

@app.route("/messages")
@login_required
def messages():
    user = get_current_user()
    return render_template("messages.html", user=user, messages=MESSAGES)

@app.route("/legal")
@login_required
def legal():
    user = get_current_user()
    return render_template("legal.html", user=user, docs=LEGAL_DOCS)

@app.route("/settings")
@login_required
def settings():
    user = get_current_user()
    return render_template("settings.html", user=user)

@app.route("/settings/update", methods=["POST"])
@login_required
def update_settings():
    email = session["user_email"]
    USERS[email]["name"] = request.form.get("name", USERS[email]["name"])
    USERS[email]["bio"] = request.form.get("bio", USERS[email]["bio"])
    flash("Profile updated successfully!", "success")
    return redirect(url_for("settings"))

# ─── API endpoints ─────────────────────────────────────────────────────────────
@app.route("/api/apply/<project_id>", methods=["POST"])
@login_required
def apply_project(project_id):
    project = next((p for p in PROJECTS if p["id"] == project_id), None)
    if project:
        return jsonify({"success": True, "message": f"Applied to {project['name']}!"})
    return jsonify({"success": False}), 404

@app.route("/api/stats")
@login_required
def api_stats():
    return jsonify({
        "proposals": len(PROPOSALS),
        "equity_value": sum(h["value"] for h in EQUITY_HOLDINGS),
        "trust_score": get_current_user()["trust_score"],
        "active_deals": 2
    })

if __name__ == "__main__":
    app.run(debug=True, port=5000)

