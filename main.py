"""RiseUp Boost backend. Run:  ADMIN_EMAIL=you@x.com ADMIN_PASSWORD='long-pass' uvicorn main:app"""
import hashlib, os, secrets, sqlite3, time
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse


DB = os.environ.get("DB_PATH", "boost.db")
RATES = {"Instagram": 0.02, "TikTok": 0.025, "YouTube": 0.04, "Facebook": 0.015}  # price per follower
STATUSES = ["Pending", "Processing", "Completed", "Cancelled"]
SESSION_TTL = 7 * 24 * 3600

def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def hash_pw(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex()

def init():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE, pw TEXT, salt TEXT, is_admin INT DEFAULT 0);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INT, expires REAL);
        CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY, user_id INT, name TEXT, platform TEXT, followers INT, link TEXT, total REAL, status TEXT DEFAULT 'Pending', created REAL);
        """)
        email = os.environ.get("ADMIN_EMAIL", "").lower()
        if email and not c.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            pw = os.environ.get("ADMIN_PASSWORD") or secrets.token_urlsafe(12)
            salt = secrets.token_hex(16)
            c.execute("INSERT INTO users(name,email,pw,salt,is_admin) VALUES('Admin',?,?,?,1)", (email, hash_pw(pw, salt), salt))
            if not os.environ.get("ADMIN_PASSWORD"):
                print(f"Admin created: {email} / {pw}  (shown once)")

init()
app = FastAPI()

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

@app.get("/")
async def home():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

app.mount(
    "/static",
    StaticFiles(directory=STATIC_DIR, check_dir=False),
    name="static"
)

def current_user(authorization: str = Header(default="")):
    token = authorization.removeprefix("Bearer ").strip()
    with db() as c:
        row = c.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>?", (token, time.time())).fetchone()
    if not row:
        raise HTTPException(401, "Please log in.")
    return dict(row)

def admin_only(u=Depends(current_user)):
    if not u["is_admin"]:
        raise HTTPException(403, "Admins only.")
    return u

def start_session(c, uid):
    t = secrets.token_urlsafe(32)
    c.execute("INSERT INTO sessions VALUES(?,?,?)", (t, uid, time.time() + SESSION_TTL))
    return t

def public(u):
    return {"id": u["id"], "name": u["name"], "email": u["email"], "is_admin": bool(u["is_admin"])}

class Register(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=5, max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=128)

class Login(BaseModel):
    email: str
    password: str

class OrderIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    platform: str
    followers: int = Field(ge=100, le=50000)
    link: str = Field(max_length=500, pattern=r"^https?://[^\s]+\.[^\s]+$")

class StatusIn(BaseModel):
    status: str

@app.post("/api/register")
def register(b: Register):
    salt = secrets.token_hex(16)
    with db() as c:
        try:
            cur = c.execute("INSERT INTO users(name,email,pw,salt) VALUES(?,?,?,?)", (b.name.strip(), b.email.lower(), hash_pw(b.password, salt), salt))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "That email is already registered.")
        u = dict(c.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone())
        return {"token": start_session(c, u["id"]), "user": public(u)}

@app.post("/api/login")
def login(b: Login):
    with db() as c:
        u = c.execute("SELECT * FROM users WHERE email=?", (b.email.lower(),)).fetchone()
        ok = u and secrets.compare_digest(u["pw"], hash_pw(b.password, u["salt"]))
        if not ok:
            raise HTTPException(401, "Wrong email or password.")
        return {"token": start_session(c, u["id"]), "user": public(dict(u))}

@app.post("/api/logout")
def logout(authorization: str = Header(default="")):
    with db() as c:
        c.execute("DELETE FROM sessions WHERE token=?", (authorization.removeprefix("Bearer ").strip(),))
    return {"ok": True}

@app.get("/api/me")
def me(u=Depends(current_user)):
    return public(u)

@app.post("/api/orders")
def create_order(b: OrderIn, u=Depends(current_user)):
    if b.platform not in RATES:
        raise HTTPException(422, "Unknown platform.")
    o = {"id": "RB-" + secrets.token_hex(3).upper(), "user_id": u["id"], "name": b.name.strip(), "platform": b.platform,
         "followers": b.followers, "link": b.link, "total": round(b.followers * RATES[b.platform], 2), "status": "Pending", "created": time.time()}
    with db() as c:
        c.execute("INSERT INTO orders VALUES(:id,:user_id,:name,:platform,:followers,:link,:total,:status,:created)", o)
    return o

@app.get("/api/orders")
def list_orders(u=Depends(current_user)):
    with db() as c:
        if u["is_admin"]:
            rows = c.execute("SELECT o.*, u.email FROM orders o JOIN users u ON u.id=o.user_id ORDER BY created DESC").fetchall()
        else:
            rows = c.execute("SELECT o.*, u.email FROM orders o JOIN users u ON u.id=o.user_id WHERE o.user_id=? ORDER BY created DESC", (u["id"],)).fetchall()
    return [dict(r) for r in rows]

@app.patch("/api/orders/{oid}")
def set_status(oid: str, b: StatusIn, _=Depends(admin_only)):
    if b.status not in STATUSES:
        raise HTTPException(422, "Unknown status.")
    with db() as c:
        if not c.execute("UPDATE orders SET status=? WHERE id=?", (b.status, oid)).rowcount:
            raise HTTPException(404, "Order not found.")
    return {"ok": True}



