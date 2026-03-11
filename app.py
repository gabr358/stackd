"""
stackd - Full Flask Application with Gemini AI + Google OAuth
"""
import os
import json
import sqlite3
import hashlib
import secrets
import datetime
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for,
                   session, jsonify, flash, g, send_from_directory)
from werkzeug.utils import secure_filename
from authlib.integrations.flask_client import OAuth

app = Flask(__name__)
app.secret_key = 'b3c1a2d4e5f6789012345678901234567890abcdef1234567890abcdef123456'
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'zip', 'doc', 'docx'}
DATABASE = os.path.join(os.path.dirname(__file__), 'stackd.db')

# ─── GOOGLE OAUTH CONFIG ──────────────────────────────────────────────────────

GOOGLE_CLIENT_ID     = '608722125549-pujkihkc3nv01j8nn38mlgv33q6l8n4k.apps.googleusercontent.com'
GOOGLE_CLIENT_SECRET = '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'

oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)

# ─── EMAIL CONFIG ─────────────────────────────────────────────────────────────

EMAIL_ADDRESS  = 'ammarsarhan007@gmail.com'
EMAIL_PASSWORD = 'uzqz wxfy zefa bbgl'
EMAIL_CONFIGURED = bool(EMAIL_ADDRESS and EMAIL_PASSWORD)

def send_email(to_address, subject, html_body):
    """Send an HTML email via Gmail SMTP. Returns (ok, error_msg)."""
    if not EMAIL_CONFIGURED:
        print(f"\n📧 [DEV MODE — email not sent]\nTo: {to_address}\nSubject: {subject}\n")
        return False, "Email not configured. Set EMAIL_ADDRESS and EMAIL_PASSWORD env vars."
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = f"stackd <{EMAIL_ADDRESS}>"
        msg['To']      = to_address
        msg.attach(MIMEText(html_body, 'html'))
        with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=10) as smtp:
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.sendmail(EMAIL_ADDRESS, to_address, msg.as_string())
        return True, None
    except smtplib.SMTPAuthenticationError:
        return False, "Gmail authentication failed. Check your App Password."
    except Exception as e:
        return False, str(e)

def create_token(email, token_type, hours=24):
    db = get_db()
    db.execute("UPDATE email_tokens SET used=1 WHERE email=? AND type=? AND used=0",
               [email.lower(), token_type])
    token = secrets.token_urlsafe(32)
    expires = (datetime.datetime.utcnow() + datetime.timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')
    db.execute("INSERT INTO email_tokens (email, token, type, expires_at) VALUES (?,?,?,?)",
               [email.lower(), token, token_type, expires])
    db.commit()
    return token

def verify_token(token, token_type):
    db = get_db()
    row = db.execute(
        "SELECT * FROM email_tokens WHERE token=? AND type=? AND used=0",
        [token, token_type]
    ).fetchone()
    if not row:
        return None
    expires = datetime.datetime.strptime(row['expires_at'], '%Y-%m-%d %H:%M:%S')
    if datetime.datetime.utcnow() > expires:
        return None
    return row['email']

def consume_token(token, token_type):
    email = verify_token(token, token_type)
    if email:
        get_db().execute("UPDATE email_tokens SET used=1 WHERE token=? AND type=?",
                         [token, token_type])
        get_db().commit()
    return email

def email_verify_html(name, verify_url):
    return f"""
<!DOCTYPE html><html><body style="font-family:'DM Sans',Arial,sans-serif;background:#F8F9F6;margin:0;padding:40px 20px;">
<div style="max-width:520px;margin:0 auto;background:white;border-radius:20px;overflow:hidden;box-shadow:0 4px 24px rgba(26,74,74,0.1);">
  <div style="background:linear-gradient(135deg,#1A4A4A,#2D6B6B);padding:36px 40px;text-align:center;">
    <div style="font-family:Georgia,serif;font-size:28px;font-weight:600;color:white;">stackd</div>
    <div style="font-size:40px;margin-top:16px;">✉️</div>
  </div>
  <div style="padding:40px;">
    <h2 style="font-family:Georgia,serif;font-size:26px;font-weight:400;color:#1A4A4A;margin:0 0 12px;">Verify your email, {name}!</h2>
    <p style="font-size:15px;color:#9BA89C;line-height:1.7;font-weight:300;margin:0 0 28px;">Thanks for joining stackd. Click the button below to verify your email address and activate your account.</p>
    <a href="{verify_url}" style="display:block;background:#1A4A4A;color:white;text-decoration:none;text-align:center;padding:16px 24px;border-radius:50px;font-size:15px;font-weight:500;margin-bottom:28px;">Verify My Email →</a>
    <p style="font-size:12px;color:#9BA89C;text-align:center;margin:0;">This link expires in 24 hours.<br>If you didn't create an account, ignore this email.</p>
    <hr style="border:none;border-top:1px solid #EDF0EC;margin:28px 0 0;">
    <p style="font-size:11px;color:#C5C5C5;text-align:center;margin:16px 0 0;">stackd · Connecting founders with specialists</p>
  </div>
</div>
</body></html>"""

def email_reset_html(name, reset_url):
    return f"""
<!DOCTYPE html><html><body style="font-family:'DM Sans',Arial,sans-serif;background:#F8F9F6;margin:0;padding:40px 20px;">
<div style="max-width:520px;margin:0 auto;background:white;border-radius:20px;overflow:hidden;box-shadow:0 4px 24px rgba(26,74,74,0.1);">
  <div style="background:linear-gradient(135deg,#1A4A4A,#2D6B6B);padding:36px 40px;text-align:center;">
    <div style="font-family:Georgia,serif;font-size:28px;font-weight:600;color:white;">stackd</div>
    <div style="font-size:40px;margin-top:16px;">🔐</div>
  </div>
  <div style="padding:40px;">
    <h2 style="font-family:Georgia,serif;font-size:26px;font-weight:400;color:#1A4A4A;margin:0 0 12px;">Reset your password, {name}</h2>
    <p style="font-size:15px;color:#9BA89C;line-height:1.7;font-weight:300;margin:0 0 28px;">We received a request to reset your stackd password. Click the button below — this link expires in 1 hour.</p>
    <a href="{reset_url}" style="display:block;background:#1A4A4A;color:white;text-decoration:none;text-align:center;padding:16px 24px;border-radius:50px;font-size:15px;font-weight:500;margin-bottom:28px;">Reset My Password →</a>
    <p style="font-size:12px;color:#9BA89C;text-align:center;margin:0;">If you didn't request this, you can safely ignore this email. Your password won't change.</p>
    <hr style="border:none;border-top:1px solid #EDF0EC;margin:28px 0 0;">
    <p style="font-size:11px;color:#C5C5C5;text-align:center;margin:16px 0 0;">stackd · Connecting founders with specialists</p>
  </div>
</div>
</body></html>"""

# ─── DATABASE ────────────────────────────────────────────────────────────────

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

def modify_db(query, args=()):
    db = get_db()
    cur = db.execute(query, args)
    db.commit()
    return cur.lastrowid

def init_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")

    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','founder','specialist')),
            avatar TEXT DEFAULT '',
            company TEXT DEFAULT '',
            bio TEXT DEFAULT '',
            skills TEXT DEFAULT '[]',
            cv_file TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            founder_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            skills_needed TEXT DEFAULT '[]',
            deadline TEXT DEFAULT '',
            status TEXT DEFAULT 'open' CHECK(status IN ('open','closed')),
            attachment TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (founder_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            specialist_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            highlighted_skills TEXT DEFAULT '[]',
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending','accepted','rejected')),
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE,
            FOREIGN KEY (specialist_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(post_id, specialist_id)
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_id INTEGER NOT NULL,
            to_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            read INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (from_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (to_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS ai_chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS email_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            token TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('verify','reset')),
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    db.commit()

    # Add columns if they don't exist yet (safe migrations)
    for col, definition in [
        ('verified', 'INTEGER DEFAULT 0'),
        ('auth_provider', "TEXT DEFAULT 'email'"),
        ('avatar_url', "TEXT DEFAULT ''"),
    ]:
        try:
            db.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
            db.commit()
        except Exception:
            pass

    admin = db.execute("SELECT id FROM users WHERE email = 'admin@gmail.com'").fetchone()
    if not admin:
        pw = hashlib.sha256('Admin123'.encode()).hexdigest()
        db.execute("INSERT INTO users (name, email, password_hash, role, verified) VALUES (?,?,?,?,1)",
                   ('Admin', 'admin@gmail.com', pw, 'admin'))
        db.commit()
    db.close()

# ─── AUTH HELPERS ─────────────────────────────────────────────────────────────

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def check_password(pw, hashed):
    return hashlib.sha256(pw.encode()).hexdigest() == hashed

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            user = query_db("SELECT role FROM users WHERE id=?", [session['user_id']], one=True)
            if not user or user['role'] not in roles:
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated
    return decorator

def get_current_user():
    if 'user_id' not in session:
        return None
    return query_db("SELECT * FROM users WHERE id=?", [session['user_id']], one=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def row_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, str):
            try:
                if v.startswith('[') or v.startswith('{'):
                    d[k] = json.loads(v)
            except Exception:
                pass
    return d

def rows_to_dicts(rows):
    return [row_to_dict(r) for r in rows]

def save_upload(file_obj, subfolder):
    if file_obj and file_obj.filename and allowed_file(file_obj.filename):
        filename = secrets.token_hex(8) + '_' + secure_filename(file_obj.filename)
        path = os.path.join(app.config['UPLOAD_FOLDER'], subfolder, filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        file_obj.save(path)
        return filename
    return ''

def redirect_by_role(role):
    """Helper to redirect user to their dashboard based on role."""
    if role == 'admin':
        return redirect(url_for('admin_dashboard'))
    elif role == 'founder':
        return redirect(url_for('founder_dashboard'))
    else:
        return redirect(url_for('specialist_dashboard'))

# ─── GROQ AI ──────────────────────────────────────────────────────────────────

GROQ_API_KEY = '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'
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL   = "llama-3.3-70b-versatile"

def call_gemini(messages_list, system_prompt):
    """Call Groq API (OpenAI-compatible) — free & very fast"""
    api_key = GROQ_API_KEY or os.environ.get('GROQ_API_KEY', '')

    if not api_key:
        return ("Hi! I'm **Shalaby**, your stackd AI assistant. 👋\n\n"
                "To activate me, open `app.py` and set your `GROQ_API_KEY`.")

    messages = [{"role": "system", "content": system_prompt}]
    for msg in messages_list:
        role = msg['role']
        if role not in ('user', 'assistant'):
            role = 'user'
        text = msg['content'].strip()
        if text:
            messages.append({"role": role, "content": text})

    if not messages or messages[-1]['role'] != 'user':
        return "Please send a message to get started!"

    try:
        response = requests.post(
            GROQ_API_URL,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
            },
            json={
                "model": GROQ_MODEL,
                "messages": messages,
                "max_tokens": 1024,
                "temperature": 0.75,
                "top_p": 0.9,
                "stream": False
            },
            timeout=30
        )
        data = response.json()
        if response.status_code != 200:
            err = data.get('error', {}).get('message', str(data))
            return f"**AI Error:** {err}"
        return data['choices'][0]['message']['content']
    except requests.exceptions.ConnectionError:
        return "**Connection Error:** Could not reach Groq. Check your internet."
    except requests.exceptions.Timeout:
        return "**Timeout:** Groq took too long. Please try again."
    except Exception as e:
        return f"**Unexpected Error:** {str(e)}"

def build_ai_system_prompt(user, context_data):
    role = user['role']
    name = user['name']

    skills_raw = user.get('skills', [])
    if isinstance(skills_raw, str):
        try: skills_raw = json.loads(skills_raw)
        except: skills_raw = []

    posts_info = ""
    apps_info = ""

    if role == 'founder':
        my_posts = context_data.get('my_posts', [])
        my_applications = context_data.get('my_applications', [])
        posts_info = "\n".join([
            f"- Post #{p['id']}: '{p['title']}' | Skills: {p['skills_needed']} | Status: {p['status']} | Deadline: {p['deadline']} | Applications: {p.get('app_count', 0)}"
            for p in my_posts
        ]) or "No posts yet."
        apps_info = "\n".join([
            f"- Specialist: {a['specialist_name']} | Skills: {a['specialist_skills']} | Status: {a['status']} | Applied to: '{a['post_title']}' | Message: {a['message'][:100]}..."
            for a in my_applications
        ]) or "No applications yet."

    elif role == 'specialist':
        my_apps = context_data.get('my_applications', [])
        open_posts = context_data.get('open_posts', [])
        apps_info = "\n".join([
            f"- Post: '{a['post_title']}' by {a['founder_name']} | Status: {a['status']} | Applied: {a['created_at'][:10]}"
            for a in my_apps
        ]) or "No applications yet."
        posts_info = "\n".join([
            f"- #{p['id']}: '{p['title']}' by {p['founder_name']} ({p.get('founder_company','')}) | Skills: {p['skills_needed']} | Deadline: {p['deadline']}"
            for p in open_posts[:10]
        ]) or "No open posts."

    platform_stats = context_data.get('stats', {})

    return f"""You are Shalaby, the stackd AI Assistant — a brilliant, warm, and deeply insightful advisor embedded in the stackd platform. stackd connects startup founders with specialist freelancers through skill-exchange.

Your personality: You are sharp, encouraging, and genuinely helpful. You give real, actionable advice — not generic platitudes. You reference the user's actual data when relevant. You're like a trusted advisor who knows the platform inside out.

CURRENT USER:
- Name: {name}
- Role: {role.capitalize()}
- Company/Skills: {user.get('company', '') or ', '.join(skills_raw) if isinstance(skills_raw, list) else skills_raw}
- Bio: {user.get('bio', 'Not set')}

PLATFORM STATS (LIVE):
- Total Users: {platform_stats.get('total_users', 0)}
- Total Posts: {platform_stats.get('total_posts', 0)}
- Total Applications: {platform_stats.get('total_applications', 0)}
- Open Posts: {platform_stats.get('open_posts', 0)}

{"FOUNDER CONTEXT:" if role == "founder" else "SPECIALIST CONTEXT:"}
{"My Posts:\n" + posts_info if role in ["founder"] else "Open Opportunities:\n" + posts_info}

{"Applications Received:\n" + apps_info if role == "founder" else "My Applications:\n" + apps_info}

YOUR CAPABILITIES:
1. Help founders evaluate specialist applicants
2. Help specialists evaluate founder posts
3. Advise on crafting better posts or applications
4. Analyze compatibility between founders and specialists
5. Give tips on collaboration, equity rates, deadlines
6. Answer questions about the platform
7. Provide strategic career/business advice

BEHAVIOR:
- Be friendly, concise, and genuinely helpful
- Reference real data from the user's account when relevant
- Use **bold** for emphasis and bullet points for lists
- Keep responses focused and under 350 words unless detail is needed
- Always be encouraging and constructive
- Sign off warmly as Shalaby
"""

# ─── ROUTES: AUTH ─────────────────────────────────────────────────────────────

@app.route('/')
def index():
    stats = {}
    if os.path.exists(DATABASE):
        try:
            stats = {
                'total_users': query_db("SELECT COUNT(*) as c FROM users WHERE role != 'admin'", one=True)['c'],
                'total_posts': query_db("SELECT COUNT(*) as c FROM posts", one=True)['c'],
                'total_applications': query_db("SELECT COUNT(*) as c FROM applications", one=True)['c'],
                'accepted_applications': query_db("SELECT COUNT(*) as c FROM applications WHERE status='accepted'", one=True)['c'],
            }
        except:
            pass
    return render_template('index.html', stats=stats)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        user = get_current_user()
        if user:
            return redirect_by_role(user['role'])

    error = None
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = query_db("SELECT * FROM users WHERE LOWER(email)=?", [email], one=True)
        if user and check_password(password, user['password_hash']):
            if EMAIL_CONFIGURED and not user['verified']:
                error = 'Please verify your email before signing in. Check your inbox.'
            else:
                session['user_id'] = user['id']
                session['user_role'] = user['role']
                session['user_name'] = user['name']
                return redirect_by_role(user['role'])
        else:
            error = 'Invalid email or password.'
    return render_template('login.html', error=error)

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    error = None
    prefill_role = request.args.get('role', 'founder')
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        role = request.form.get('role', 'founder')
        company = request.form.get('company', '').strip()
        skills_raw = request.form.get('skills', '')
        bio = request.form.get('bio', '').strip()

        if not name or not email or not password:
            error = 'All fields are required.'
        elif password != confirm:
            error = 'Passwords do not match.'
        elif len(password) < 6:
            error = 'Password must be at least 6 characters.'
        elif query_db("SELECT id FROM users WHERE LOWER(email)=?", [email], one=True):
            error = 'An account with this email already exists.'
        else:
            skills_list = [s.strip() for s in skills_raw.split(',') if s.strip()]
            avatar = name[0].upper()

            avatar_file = request.files.get('avatar')
            avatar_filename = save_upload(avatar_file, 'avatars')

            cv_file = request.files.get('cv')
            cv_filename = save_upload(cv_file, 'cvs')

            pw_hash = hash_password(password)
            uid = modify_db(
                "INSERT INTO users (name, email, password_hash, role, avatar, company, bio, skills, cv_file, verified) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (name, email, pw_hash, role, avatar_filename or avatar, company,
                 bio, json.dumps(skills_list), cv_filename, 0)
            )

            token = create_token(email, 'verify')
            verify_url = url_for('verify_email', token=token, _external=True)
            ok, err = send_email(
                email,
                "Verify your stackd account ✉️",
                email_verify_html(name, verify_url)
            )

            if EMAIL_CONFIGURED:
                flash('Account created! Please check your email to verify your account before signing in.', 'success')
                return redirect(url_for('login'))
            else:
                session['user_id'] = uid
                session['user_role'] = role
                session['user_name'] = name
                modify_db("UPDATE users SET verified=1 WHERE id=?", [uid])
                flash('Account created! (Email verification skipped — dev mode)', 'success')
                return redirect_by_role(role)

    return render_template('signup.html', error=error, prefill_role=prefill_role)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ─── GOOGLE OAUTH ROUTES ──────────────────────────────────────────────────────

@app.route('/auth/google')
def google_login():
    """Redirect the user to Google's login page."""
    redirect_uri = url_for('google_callback', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/google/callback')
def google_callback():
    """Google redirects back here after the user logs in."""
    try:
        token = google.authorize_access_token()
    except Exception as e:
        flash('Google login failed. Please try again.', 'error')
        return redirect(url_for('login'))

    user_info = token.get('userinfo')
    if not user_info:
        flash('Could not retrieve your Google account info. Please try again.', 'error')
        return redirect(url_for('login'))

    email      = user_info['email'].lower()
    name       = user_info.get('name', email.split('@')[0])
    avatar_url = user_info.get('picture', '')

    # Check if a user with this email already exists
    existing_user = query_db("SELECT * FROM users WHERE LOWER(email)=?", [email], one=True)

    if existing_user:
        # User exists — just log them in, no matter how they registered
        user = existing_user
        # If they previously registered with email, mark them as verified now
        if not user['verified']:
            modify_db("UPDATE users SET verified=1 WHERE id=?", [user['id']])
    else:
        # Brand new user — create their account automatically
        # Default role is 'specialist'; they can change it in their profile
        default_role = 'specialist'
        uid = modify_db(
            """INSERT INTO users
               (name, email, password_hash, role, avatar, bio, skills, verified, auth_provider, avatar_url)
               VALUES (?,?,?,?,?,?,?,1,'google',?)""",
            (name, email,
             hash_password(secrets.token_hex(16)),  # random unusable password
             default_role,
             avatar_url or name[0].upper(),         # use Google photo URL as avatar
             '', '[]',
             avatar_url)
        )
        user = query_db("SELECT * FROM users WHERE id=?", [uid], one=True)

    # Set the session
    session['user_id']   = user['id']
    session['user_role'] = user['role']
    session['user_name'] = user['name']

    flash(f'Welcome, {user["name"]}! You are signed in with Google.', 'success')
    return redirect_by_role(user['role'])

# ─── PASSWORD RESET ROUTES ────────────────────────────────────────────────────

@app.route('/forgot-password/reset', methods=['POST'])
def forgot_password_reset():
    data = request.get_json()
    email = data.get('email', '').strip().lower()
    new_password = data.get('password', '')
    if not email or not new_password or len(new_password) < 6:
        return jsonify({'ok': False, 'error': 'Invalid data'})
    user = query_db("SELECT id FROM users WHERE LOWER(email)=?", [email], one=True)
    if not user:
        return jsonify({'ok': False, 'error': 'No account found with that email'})
    modify_db("UPDATE users SET password_hash=? WHERE LOWER(email)=?",
              [hash_password(new_password), email])
    return jsonify({'ok': True})

@app.route('/forgot-password/send', methods=['POST'])
def forgot_password_send():
    data = request.get_json()
    email = (data.get('email') or '').strip().lower()
    if not email:
        return jsonify({'ok': False, 'error': 'Please enter your email address.'})

    user = query_db("SELECT id, name FROM users WHERE LOWER(email)=?", [email], one=True)
    if user:
        token = create_token(email, 'reset', hours=1)
        reset_url = url_for('reset_password_page', token=token, _external=True)
        ok, err = send_email(
            email,
            "Reset your stackd password 🔐",
            email_reset_html(user['name'], reset_url)
        )
        if not ok and EMAIL_CONFIGURED:
            return jsonify({'ok': False, 'error': f'Could not send email: {err}'})
        if not EMAIL_CONFIGURED:
            print(f"\n🔗 [DEV] Reset link: {reset_url}\n")
    return jsonify({'ok': True})

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password_page(token):
    email = verify_token(token, 'reset')
    if not email:
        return render_template('reset_password.html', error='This link has expired or is invalid. Please request a new one.', token=None)

    error = None
    success = False
    if request.method == 'POST':
        pw1 = request.form.get('password', '')
        pw2 = request.form.get('confirm_password', '')
        if len(pw1) < 6:
            error = 'Password must be at least 6 characters.'
        elif pw1 != pw2:
            error = 'Passwords do not match.'
        else:
            consumed = consume_token(token, 'reset')
            if not consumed:
                error = 'This link has already been used. Please request a new one.'
            else:
                modify_db("UPDATE users SET password_hash=? WHERE LOWER(email)=?",
                          [hash_password(pw1), email])
                success = True
    return render_template('reset_password.html', error=error, success=success, token=token, email=email)

@app.route('/verify-email/<token>')
def verify_email(token):
    email = consume_token(token, 'verify')
    if not email:
        return render_template('verify_email.html', success=False,
                               message='This verification link has expired or already been used.')
    modify_db("UPDATE users SET verified=1 WHERE LOWER(email)=?", [email])
    return render_template('verify_email.html', success=True,
                           message='Your email has been verified! You can now sign in.')

@app.route('/verify-email/resend', methods=['POST'])
def resend_verification():
    data = request.get_json()
    email = (data.get('email') or '').strip().lower()
    if not email:
        return jsonify({'ok': False, 'error': 'No email provided.'})
    user = query_db("SELECT id, name, verified FROM users WHERE LOWER(email)=?", [email], one=True)
    if not user:
        return jsonify({'ok': True})
    if user['verified']:
        return jsonify({'ok': False, 'error': 'This email is already verified.'})
    token = create_token(email, 'verify')
    verify_url = url_for('verify_email', token=token, _external=True)
    ok, err = send_email(email, "Verify your stackd account ✉️",
                         email_verify_html(user['name'], verify_url))
    if not ok and EMAIL_CONFIGURED:
        return jsonify({'ok': False, 'error': f'Could not send email: {err}'})
    if not EMAIL_CONFIGURED:
        print(f"\n🔗 [DEV] Verify link: {verify_url}\n")
    return jsonify({'ok': True})

# ─── ROUTES: ADMIN ────────────────────────────────────────────────────────────

@app.route('/admin')
@role_required('admin')
def admin_dashboard():
    stats = {
        'total_users': query_db("SELECT COUNT(*) as c FROM users WHERE role != 'admin'", one=True)['c'],
        'founders': query_db("SELECT COUNT(*) as c FROM users WHERE role='founder'", one=True)['c'],
        'specialists': query_db("SELECT COUNT(*) as c FROM users WHERE role='specialist'", one=True)['c'],
        'total_posts': query_db("SELECT COUNT(*) as c FROM posts", one=True)['c'],
        'open_posts': query_db("SELECT COUNT(*) as c FROM posts WHERE status='open'", one=True)['c'],
        'total_applications': query_db("SELECT COUNT(*) as c FROM applications", one=True)['c'],
        'pending_apps': query_db("SELECT COUNT(*) as c FROM applications WHERE status='pending'", one=True)['c'],
        'accepted_apps': query_db("SELECT COUNT(*) as c FROM applications WHERE status='accepted'", one=True)['c'],
        'total_messages': query_db("SELECT COUNT(*) as c FROM messages", one=True)['c'],
    }
    users = rows_to_dicts(query_db("SELECT * FROM users WHERE role != 'admin' ORDER BY created_at DESC"))
    posts = rows_to_dicts(query_db("""
        SELECT p.*, u.name as founder_name,
               (SELECT COUNT(*) FROM applications WHERE post_id=p.id) as app_count
        FROM posts p JOIN users u ON p.founder_id=u.id ORDER BY p.created_at DESC
    """))
    applications = rows_to_dicts(query_db("""
        SELECT a.*, u.name as specialist_name, p.title as post_title, f.name as founder_name
        FROM applications a
        JOIN users u ON a.specialist_id=u.id
        JOIN posts p ON a.post_id=p.id
        JOIN users f ON p.founder_id=f.id
        ORDER BY a.created_at DESC
    """))
    chart_labels = []
    chart_users = []
    chart_posts = []
    for i in range(13, -1, -1):
        d = (datetime.datetime.now() - datetime.timedelta(days=i)).strftime('%Y-%m-%d')
        label = (datetime.datetime.now() - datetime.timedelta(days=i)).strftime('%b %d')
        u_count = query_db("SELECT COUNT(*) as c FROM users WHERE DATE(created_at)=?", [d], one=True)['c']
        p_count = query_db("SELECT COUNT(*) as c FROM posts WHERE DATE(created_at)=?", [d], one=True)['c']
        chart_labels.append(label)
        chart_users.append(u_count)
        chart_posts.append(p_count)

    return render_template('dashboards/admin.html',
                           stats=stats, users=users, posts=posts,
                           applications=applications,
                           chart_labels=json.dumps(chart_labels),
                           chart_users=json.dumps(chart_users),
                           chart_posts=json.dumps(chart_posts))

@app.route('/admin/delete_user/<int:uid>', methods=['POST'])
@role_required('admin')
def admin_delete_user(uid):
    modify_db("DELETE FROM users WHERE id=? AND role != 'admin'", [uid])
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_post/<int:pid>', methods=['POST'])
@role_required('admin')
def admin_delete_post(pid):
    modify_db("DELETE FROM posts WHERE id=?", [pid])
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_application/<int:aid>', methods=['POST'])
@role_required('admin')
def admin_delete_application(aid):
    modify_db("DELETE FROM applications WHERE id=?", [aid])
    return redirect(url_for('admin_dashboard'))

# ─── ROUTES: FOUNDER ──────────────────────────────────────────────────────────

@app.route('/founder')
@role_required('founder')
def founder_dashboard():
    user = get_current_user()
    uid = user['id']
    my_posts = rows_to_dicts(query_db("""
        SELECT p.*, (SELECT COUNT(*) FROM applications WHERE post_id=p.id) as app_count
        FROM posts p WHERE p.founder_id=? ORDER BY p.created_at DESC
    """, [uid]))
    post_ids = [p['id'] for p in my_posts]

    applications = []
    if post_ids:
        placeholders = ','.join(['?'] * len(post_ids))
        applications = rows_to_dicts(query_db(f"""
            SELECT a.*, u.name as specialist_name, u.skills as specialist_skills,
                   u.bio as specialist_bio, u.avatar as spec_avatar,
                   u.cv_file as spec_cv, u.id as specialist_id, p.title as post_title
            FROM applications a
            JOIN users u ON a.specialist_id=u.id
            JOIN posts p ON a.post_id=p.id
            WHERE a.post_id IN ({placeholders})
            ORDER BY a.created_at DESC
        """, post_ids))

    conversations = rows_to_dicts(query_db("""
        SELECT DISTINCT
            CASE WHEN m.from_id=? THEN m.to_id ELSE m.from_id END as partner_id,
            u.name as partner_name, u.avatar as partner_avatar, u.role as partner_role,
            (SELECT content FROM messages WHERE (from_id=? AND to_id=u.id) OR (from_id=u.id AND to_id=?) ORDER BY created_at DESC LIMIT 1) as last_message,
            (SELECT COUNT(*) FROM messages WHERE from_id=u.id AND to_id=? AND read=0) as unread_count,
            (SELECT created_at FROM messages WHERE (from_id=? AND to_id=u.id) OR (from_id=u.id AND to_id=?) ORDER BY created_at DESC LIMIT 1) as last_time
        FROM messages m
        JOIN users u ON u.id = CASE WHEN m.from_id=? THEN m.to_id ELSE m.from_id END
        WHERE m.from_id=? OR m.to_id=?
        GROUP BY partner_id ORDER BY last_time DESC
    """, [uid]*9))

    stats = {
        'total_posts': len(my_posts),
        'open_posts': sum(1 for p in my_posts if p['status'] == 'open'),
        'total_applications': len(applications),
        'pending_applications': sum(1 for a in applications if a['status'] == 'pending'),
        'accepted_applications': sum(1 for a in applications if a['status'] == 'accepted'),
        'unread_messages': query_db("SELECT COUNT(*) as c FROM messages WHERE to_id=? AND read=0", [uid], one=True)['c'],
    }

    return render_template('dashboards/founder.html',
                           user=row_to_dict(user), my_posts=my_posts,
                           applications=applications, conversations=conversations,
                           stats=stats)

@app.route('/founder/post/create', methods=['POST'])
@role_required('founder')
def create_post():
    user = get_current_user()
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    skills_raw = request.form.get('skills', '')
    deadline = request.form.get('deadline', '')
    if not title or not description:
        flash('Title and description are required.', 'error')
        return redirect(url_for('founder_dashboard'))
    skills = json.dumps([s.strip() for s in skills_raw.split(',') if s.strip()])
    attachment = ''
    f = request.files.get('attachment')
    if f:
        attachment = save_upload(f, 'posts')
    modify_db("INSERT INTO posts (founder_id, title, description, skills_needed, deadline, attachment) VALUES (?,?,?,?,?,?)",
              (user['id'], title, description, skills, deadline, attachment))
    flash('Post created successfully!', 'success')
    return redirect(url_for('founder_dashboard') + '#posts')

@app.route('/founder/post/<int:pid>/close', methods=['POST'])
@role_required('founder')
def close_post(pid):
    user = get_current_user()
    modify_db("UPDATE posts SET status='closed' WHERE id=? AND founder_id=?", [pid, user['id']])
    return redirect(url_for('founder_dashboard') + '#posts')

@app.route('/founder/post/<int:pid>/open', methods=['POST'])
@role_required('founder')
def reopen_post(pid):
    user = get_current_user()
    modify_db("UPDATE posts SET status='open' WHERE id=? AND founder_id=?", [pid, user['id']])
    return redirect(url_for('founder_dashboard') + '#posts')

@app.route('/founder/post/<int:pid>/delete', methods=['POST'])
@role_required('founder')
def delete_post(pid):
    user = get_current_user()
    modify_db("DELETE FROM posts WHERE id=? AND founder_id=?", [pid, user['id']])
    flash('Post deleted.', 'success')
    return redirect(url_for('founder_dashboard') + '#posts')

@app.route('/founder/application/<int:aid>/accept', methods=['POST'])
@role_required('founder')
def accept_application(aid):
    modify_db("UPDATE applications SET status='accepted' WHERE id=?", [aid])
    flash('Application accepted!', 'success')
    return redirect(url_for('founder_dashboard') + '#applications')

@app.route('/founder/application/<int:aid>/reject', methods=['POST'])
@role_required('founder')
def reject_application(aid):
    modify_db("UPDATE applications SET status='rejected' WHERE id=?", [aid])
    return redirect(url_for('founder_dashboard') + '#applications')

# ─── ROUTES: SPECIALIST ───────────────────────────────────────────────────────

@app.route('/specialist')
@role_required('specialist')
def specialist_dashboard():
    user = get_current_user()
    uid = user['id']

    open_posts = rows_to_dicts(query_db("""
        SELECT p.*, u.name as founder_name, u.company as founder_company, u.avatar as founder_avatar,
               (SELECT COUNT(*) FROM applications WHERE post_id=p.id) as app_count
        FROM posts p JOIN users u ON p.founder_id=u.id
        WHERE p.status='open' ORDER BY p.created_at DESC
    """))

    my_applications = rows_to_dicts(query_db("""
        SELECT a.*, p.title as post_title, p.deadline as post_deadline,
               u.name as founder_name, u.company as founder_company, u.id as founder_id
        FROM applications a
        JOIN posts p ON a.post_id=p.id
        JOIN users u ON p.founder_id=u.id
        WHERE a.specialist_id=? ORDER BY a.created_at DESC
    """, [uid]))

    applied_post_ids = [a['post_id'] for a in my_applications]

    conversations = rows_to_dicts(query_db("""
        SELECT DISTINCT
            CASE WHEN m.from_id=? THEN m.to_id ELSE m.from_id END as partner_id,
            u.name as partner_name, u.avatar as partner_avatar, u.role as partner_role,
            (SELECT content FROM messages WHERE (from_id=? AND to_id=u.id) OR (from_id=u.id AND to_id=?) ORDER BY created_at DESC LIMIT 1) as last_message,
            (SELECT COUNT(*) FROM messages WHERE from_id=u.id AND to_id=? AND read=0) as unread_count,
            (SELECT created_at FROM messages WHERE (from_id=? AND to_id=u.id) OR (from_id=u.id AND to_id=?) ORDER BY created_at DESC LIMIT 1) as last_time
        FROM messages m
        JOIN users u ON u.id = CASE WHEN m.from_id=? THEN m.to_id ELSE m.from_id END
        WHERE m.from_id=? OR m.to_id=?
        GROUP BY partner_id ORDER BY last_time DESC
    """, [uid]*9))

    stats = {
        'open_posts': len(open_posts),
        'my_applications': len(my_applications),
        'accepted': sum(1 for a in my_applications if a['status'] == 'accepted'),
        'pending': sum(1 for a in my_applications if a['status'] == 'pending'),
        'unread_messages': query_db("SELECT COUNT(*) as c FROM messages WHERE to_id=? AND read=0", [uid], one=True)['c'],
    }

    return render_template('dashboards/specialist.html',
                           user=row_to_dict(user), open_posts=open_posts,
                           my_applications=my_applications, applied_post_ids=applied_post_ids,
                           conversations=conversations, stats=stats)

@app.route('/specialist/apply/<int:pid>', methods=['POST'])
@role_required('specialist')
def apply_to_post(pid):
    user = get_current_user()
    message = request.form.get('message', '').strip()
    skills_raw = request.form.get('skills', '')
    if not message:
        flash('Application message is required.', 'error')
        return redirect(url_for('specialist_dashboard'))
    skills = json.dumps([s.strip() for s in skills_raw.split(',') if s.strip()])
    try:
        modify_db("INSERT INTO applications (post_id, specialist_id, message, highlighted_skills) VALUES (?,?,?,?)",
                  (pid, user['id'], message, skills))
        flash('Application submitted!', 'success')
    except Exception:
        flash('You already applied to this post.', 'error')
    return redirect(url_for('specialist_dashboard') + '#applications')

@app.route('/specialist/withdraw/<int:aid>', methods=['POST'])
@role_required('specialist')
def withdraw_application(aid):
    user = get_current_user()
    modify_db("DELETE FROM applications WHERE id=? AND specialist_id=?", [aid, user['id']])
    flash('Application withdrawn.', 'success')
    return redirect(url_for('specialist_dashboard') + '#applications')

# ─── ROUTES: MESSAGING ────────────────────────────────────────────────────────

@app.route('/messages/<int:partner_id>')
@login_required
def messages(partner_id):
    user = get_current_user()
    uid = user['id']
    partner = query_db("SELECT * FROM users WHERE id=?", [partner_id], one=True)
    if not partner:
        return redirect(url_for(user['role'] + '_dashboard'))

    modify_db("UPDATE messages SET read=1 WHERE from_id=? AND to_id=?", [partner_id, uid])

    chat_messages = rows_to_dicts(query_db("""
        SELECT m.*, f.name as from_name, t.name as to_name
        FROM messages m
        JOIN users f ON m.from_id=f.id
        JOIN users t ON m.to_id=t.id
        WHERE (m.from_id=? AND m.to_id=?) OR (m.from_id=? AND m.to_id=?)
        ORDER BY m.created_at ASC
    """, [uid, partner_id, partner_id, uid]))

    return render_template('messages.html',
                           user=row_to_dict(user),
                           partner=row_to_dict(partner),
                           chat_messages=chat_messages)

@app.route('/messages/<int:partner_id>/send', methods=['POST'])
@login_required
def send_message(partner_id):
    user = get_current_user()
    content = request.form.get('content', '').strip()
    if content:
        modify_db("INSERT INTO messages (from_id, to_id, content) VALUES (?,?,?)",
                  [user['id'], partner_id, content])
    return redirect(url_for('messages', partner_id=partner_id))

@app.route('/api/messages/<int:partner_id>/send', methods=['POST'])
@login_required
def api_send_message(partner_id):
    user = get_current_user()
    data = request.get_json()
    content = data.get('content', '').strip()
    if content:
        modify_db("INSERT INTO messages (from_id, to_id, content) VALUES (?,?,?)",
                  [user['id'], partner_id, content])
        return jsonify({'ok': True})
    return jsonify({'ok': False})

@app.route('/api/messages/<int:partner_id>/poll')
@login_required
def poll_messages(partner_id):
    user = get_current_user()
    uid = user['id']
    after = request.args.get('after', '1970-01-01')
    modify_db("UPDATE messages SET read=1 WHERE from_id=? AND to_id=?", [partner_id, uid])
    msgs = rows_to_dicts(query_db("""
        SELECT m.id, m.from_id, m.content, m.created_at, u.name as from_name
        FROM messages m JOIN users u ON m.from_id=u.id
        WHERE ((m.from_id=? AND m.to_id=?) OR (m.from_id=? AND m.to_id=?))
          AND m.created_at > ?
        ORDER BY m.created_at ASC
    """, [uid, partner_id, partner_id, uid, after]))
    return jsonify(msgs)

# ─── ROUTES: AI CHAT ─────────────────────────────────────────────────────────

@app.route('/api/ai/chat', methods=['POST'])
@login_required
def ai_chat():
    user = get_current_user()
    uid = user['id']
    data = request.get_json()
    user_message = data.get('message', '').strip()

    if not user_message:
        return jsonify({'error': 'Empty message'}), 400

    modify_db("INSERT INTO ai_chats (user_id, role, content) VALUES (?,?,?)",
              (uid, 'user', user_message))

    context_data = _build_user_context(user, uid)

    history = rows_to_dicts(query_db(
        "SELECT role, content FROM ai_chats WHERE user_id=? ORDER BY created_at DESC LIMIT 20",
        [uid]
    ))
    history.reverse()
    messages_list = [{'role': h['role'], 'content': h['content']} for h in history]

    system_prompt = build_ai_system_prompt(row_to_dict(user), context_data)
    ai_response = call_gemini(messages_list, system_prompt)

    modify_db("INSERT INTO ai_chats (user_id, role, content) VALUES (?,?,?)",
              (uid, 'assistant', ai_response))

    return jsonify({'response': ai_response})

@app.route('/api/ai/history')
@login_required
def ai_history():
    user = get_current_user()
    history = rows_to_dicts(query_db(
        "SELECT role, content, created_at FROM ai_chats WHERE user_id=? ORDER BY created_at ASC",
        [user['id']]
    ))
    return jsonify(history)

@app.route('/api/ai/clear', methods=['POST'])
@login_required
def ai_clear():
    user = get_current_user()
    modify_db("DELETE FROM ai_chats WHERE user_id=?", [user['id']])
    return jsonify({'ok': True})

def _build_user_context(user, uid):
    user = row_to_dict(user)
    role = user['role']
    context = {
        'stats': {
            'total_users': query_db("SELECT COUNT(*) as c FROM users WHERE role != 'admin'", one=True)['c'],
            'total_posts': query_db("SELECT COUNT(*) as c FROM posts", one=True)['c'],
            'total_applications': query_db("SELECT COUNT(*) as c FROM applications", one=True)['c'],
            'open_posts': query_db("SELECT COUNT(*) as c FROM posts WHERE status='open'", one=True)['c'],
        }
    }

    if role == 'founder':
        my_posts = rows_to_dicts(query_db("""
            SELECT p.*, (SELECT COUNT(*) FROM applications WHERE post_id=p.id) as app_count
            FROM posts p WHERE p.founder_id=?
        """, [uid]))
        post_ids = [p['id'] for p in my_posts]
        apps = []
        if post_ids:
            ph = ','.join(['?'] * len(post_ids))
            apps = rows_to_dicts(query_db(f"""
                SELECT a.*, u.name as specialist_name, u.skills as specialist_skills, p.title as post_title
                FROM applications a
                JOIN users u ON a.specialist_id=u.id
                JOIN posts p ON a.post_id=p.id
                WHERE a.post_id IN ({ph})
            """, post_ids))
        context['my_posts'] = my_posts
        context['my_applications'] = apps

    elif role == 'specialist':
        my_apps = rows_to_dicts(query_db("""
            SELECT a.*, p.title as post_title, u.name as founder_name, u.company as founder_company
            FROM applications a JOIN posts p ON a.post_id=p.id JOIN users u ON p.founder_id=u.id
            WHERE a.specialist_id=?
        """, [uid]))
        open_posts = rows_to_dicts(query_db("""
            SELECT p.*, u.name as founder_name, u.company as founder_company
            FROM posts p JOIN users u ON p.founder_id=u.id
            WHERE p.status='open' LIMIT 15
        """))
        context['my_applications'] = my_apps
        context['open_posts'] = open_posts

    return context

# ─── ROUTES: PROFILE ─────────────────────────────────────────────────────────

@app.route('/profile/update', methods=['POST'])
@login_required
def update_profile():
    user = get_current_user()
    uid = user['id']
    name = request.form.get('name', '').strip()
    company = request.form.get('company', '').strip()
    bio = request.form.get('bio', '').strip()
    skills_raw = request.form.get('skills', '')
    skills = json.dumps([s.strip() for s in skills_raw.split(',') if s.strip()])

    avatar_file = request.files.get('avatar')
    avatar = user['avatar']
    if avatar_file and avatar_file.filename:
        new_av = save_upload(avatar_file, 'avatars')
        if new_av:
            avatar = new_av

    cv_file = request.files.get('cv')
    cv = user['cv_file']
    if cv_file and cv_file.filename:
        new_cv = save_upload(cv_file, 'cvs')
        if new_cv:
            cv = new_cv

    modify_db("UPDATE users SET name=?, company=?, bio=?, skills=?, avatar=?, cv_file=? WHERE id=?",
              (name, company, bio, skills, avatar, cv, uid))
    session['user_name'] = name
    flash('Profile updated!', 'success')

    if user['role'] == 'founder':
        return redirect(url_for('founder_dashboard') + '#profile')
    return redirect(url_for('specialist_dashboard') + '#profile')

# ─── SERVE UPLOADS ────────────────────────────────────────────────────────────

@app.route('/uploads/<path:filename>')
@login_required
def serve_upload(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ─── APP ENTRY ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
