"""
EquiSwap - Full Flask Application
"""
import os
import json
import sqlite3
import hashlib
import secrets
import datetime
import urllib.request
import urllib.error
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for,
                   session, jsonify, flash, g)
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'zip', 'doc', 'docx'}
DATABASE = os.path.join(os.path.dirname(__file__), 'equiswap.db')

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
    """)
    db.commit()

    # Seed admin account
    admin = db.execute("SELECT id FROM users WHERE email = 'admin@gmail.com'").fetchone()
    if not admin:
        pw = hashlib.sha256('Admin123'.encode()).hexdigest()
        db.execute("INSERT INTO users (name, email, password_hash, role) VALUES (?,?,?,?)",
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

# ─── AI CHAT ──────────────────────────────────────────────────────────────────

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

def call_claude(messages_list, system_prompt):
    """Call Claude API using only stdlib urllib"""
    # Get API key from environment variable
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return "⚠️ AI assistant not configured. Please set the ANTHROPIC_API_KEY environment variable to enable AI features."

    payload = json.dumps({
        "model": "claude-sonnet-4-5",
        "max_tokens": 1024,
        "system": system_prompt,
        "messages": messages_list
    }).encode('utf-8')

    req = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=payload,
        headers={
            'Content-Type': 'application/json',
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01'
        },
        method='POST'
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data['content'][0]['text']
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8')
        return f"AI error: {e.code} — {body[:200]}"
    except Exception as e:
        return f"AI connection error: {str(e)}"

def build_ai_system_prompt(user, context_data):
    """Build a rich system prompt with real platform context"""
    role = user['role']
    name = user['name']

    skills_raw = user['skills']
    if isinstance(skills_raw, str):
        try: skills_raw = json.loads(skills_raw)
        except: skills_raw = []

    posts_info = ""
    apps_info = ""
    specialists_info = ""
    founders_info = ""

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
            f"- #{p['id']}: '{p['title']}' by {p['founder_name']} ({p['founder_company']}) | Skills: {p['skills_needed']} | Deadline: {p['deadline']}"
            for p in open_posts[:10]
        ]) or "No open posts."

    platform_stats = context_data.get('stats', {})

    return f"""You are the EquiSwap AI Assistant — a smart, helpful advisor embedded in the EquiSwap platform, which connects startup founders with specialist freelancers through skill-exchange.

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
1. Help founders evaluate specialist applicants (based on skills, message quality, experience signals)
2. Help specialists evaluate whether a founder's post is worth applying to
3. Provide advice on crafting better posts or applications
4. Analyze compatibility between founders and specialists
5. Give tips on collaboration, rates, deadlines
6. Answer questions about the platform
7. Provide strategic career/business advice

BEHAVIOR:
- Be friendly, concise, and genuinely helpful
- Reference real data from the user's account when relevant
- If asked about a specific person or post, use the context provided above
- Be honest about limitations (e.g., you can't see private messages)
- Keep responses under 300 words unless a detailed explanation is needed
- Use bullet points for lists, bold for emphasis
- Always be encouraging and constructive
"""

# ─── ROUTES: AUTH ─────────────────────────────────────────────────────────────

@app.route('/')
def index():
    stats = {}
    if os.path.exists(DATABASE):
        stats = {
            'total_users': query_db("SELECT COUNT(*) as c FROM users WHERE role != 'admin'", one=True)['c'],
            'total_posts': query_db("SELECT COUNT(*) as c FROM posts", one=True)['c'],
            'total_applications': query_db("SELECT COUNT(*) as c FROM applications", one=True)['c'],
            'accepted_applications': query_db("SELECT COUNT(*) as c FROM applications WHERE status='accepted'", one=True)['c'],
        }
    return render_template('index.html', stats=stats)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        user = get_current_user()
        if user:
            return redirect(url_for(user['role'] + '_dashboard'))

    error = None
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = query_db("SELECT * FROM users WHERE LOWER(email)=?", [email], one=True)
        if user and check_password(password, user['password_hash']):
            session['user_id'] = user['id']
            session['user_role'] = user['role']
            session['user_name'] = user['name']
            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            elif user['role'] == 'founder':
                return redirect(url_for('founder_dashboard'))
            else:
                return redirect(url_for('specialist_dashboard'))
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

            # Handle avatar upload
            avatar_file = request.files.get('avatar')
            avatar_filename = save_upload(avatar_file, 'avatars')

            # Handle CV upload
            cv_file = request.files.get('cv')
            cv_filename = save_upload(cv_file, 'cvs')

            pw_hash = hash_password(password)
            uid = modify_db(
                "INSERT INTO users (name, email, password_hash, role, avatar, company, bio, skills, cv_file) VALUES (?,?,?,?,?,?,?,?,?)",
                (name, email, pw_hash, role, avatar_filename or avatar, company,
                 bio, json.dumps(skills_list), cv_filename)
            )
            session['user_id'] = uid
            session['user_role'] = role
            session['user_name'] = name
            if role == 'founder':
                return redirect(url_for('founder_dashboard'))
            else:
                return redirect(url_for('specialist_dashboard'))

    return render_template('signup.html', error=error, prefill_role=prefill_role)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

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
    # Chart data: signups per day last 14 days
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
                   u.cv_file as spec_cv, p.title as post_title
            FROM applications a
            JOIN users u ON a.specialist_id=u.id
            JOIN posts p ON a.post_id=p.id
            WHERE a.post_id IN ({placeholders})
            ORDER BY a.created_at DESC
        """, post_ids))

    # Conversations (unique contacts)
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
    return redirect(url_for('founder_dashboard'))

@app.route('/founder/post/<int:pid>/close', methods=['POST'])
@role_required('founder')
def close_post(pid):
    user = get_current_user()
    modify_db("UPDATE posts SET status='closed' WHERE id=? AND founder_id=?", [pid, user['id']])
    return redirect(url_for('founder_dashboard'))

@app.route('/founder/post/<int:pid>/open', methods=['POST'])
@role_required('founder')
def reopen_post(pid):
    user = get_current_user()
    modify_db("UPDATE posts SET status='open' WHERE id=? AND founder_id=?", [pid, user['id']])
    return redirect(url_for('founder_dashboard'))

@app.route('/founder/post/<int:pid>/delete', methods=['POST'])
@role_required('founder')
def delete_post(pid):
    user = get_current_user()
    modify_db("DELETE FROM posts WHERE id=? AND founder_id=?", [pid, user['id']])
    return redirect(url_for('founder_dashboard'))

@app.route('/founder/application/<int:aid>/accept', methods=['POST'])
@role_required('founder')
def accept_application(aid):
    modify_db("UPDATE applications SET status='accepted' WHERE id=?", [aid])
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
    except Exception:
        pass  # Already applied
    return redirect(url_for('specialist_dashboard'))

@app.route('/specialist/withdraw/<int:aid>', methods=['POST'])
@role_required('specialist')
def withdraw_application(aid):
    user = get_current_user()
    modify_db("DELETE FROM applications WHERE id=? AND specialist_id=?", [aid, user['id']])
    return redirect(url_for('specialist_dashboard'))

# ─── ROUTES: MESSAGING ────────────────────────────────────────────────────────

@app.route('/messages/<int:partner_id>')
@login_required
def messages(partner_id):
    user = get_current_user()
    uid = user['id']
    partner = query_db("SELECT * FROM users WHERE id=?", [partner_id], one=True)
    if not partner:
        return redirect(url_for(user['role'] + '_dashboard'))

    # Mark as read
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

    # Save user message to DB
    modify_db("INSERT INTO ai_chats (user_id, role, content) VALUES (?,?,?)",
              (uid, 'user', user_message))

    # Build context
    context_data = _build_user_context(user, uid)

    # Get chat history (last 10 exchanges)
    history = rows_to_dicts(query_db(
        "SELECT role, content FROM ai_chats WHERE user_id=? ORDER BY created_at DESC LIMIT 20",
        [uid]
    ))
    history.reverse()
    # Build messages list for Claude
    messages_list = [{'role': h['role'], 'content': h['content']} for h in history]

    system_prompt = build_ai_system_prompt(row_to_dict(user), context_data)

    # Call Claude
    ai_response = call_claude(messages_list, system_prompt)

    # Save AI response
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

    if user['role'] == 'founder':
        return redirect(url_for('founder_dashboard') + '#profile')
    return redirect(url_for('specialist_dashboard') + '#profile')

# ─── APP ENTRY ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    print("\n" + "="*55)
    print("  EquiSwap is running at http://127.0.0.1:5000")
    print("  Admin login: admin@gmail.com / Admin123")
    print("="*55 + "\n")
    app.run(debug=True, port=5000)
