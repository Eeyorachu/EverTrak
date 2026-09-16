import os
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import psycopg
from psycopg.rows import dict_row
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
DATABASE_URL = os.environ["DATABASE_URL"]
APP_PASSWORD = os.environ["APP_PASSWORD"]
app.config.update(SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  PERMANENT_SESSION_LIFETIME=timedelta(hours=12))

def db():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)

def init_db():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS bids(
          id BIGSERIAL PRIMARY KEY,bid_number TEXT NOT NULL,project_name TEXT NOT NULL,closing_date DATE NOT NULL,
          closing_time TIME,client TEXT DEFAULT '',address TEXT DEFAULT '',notes TEXT DEFAULT '',
          status TEXT DEFAULT 'active',dollar_value NUMERIC(14,2) DEFAULT 0,
          created_at TIMESTAMPTZ DEFAULT now(),updated_at TIMESTAMPTZ DEFAULT now())""")
        c.execute("""CREATE TABLE IF NOT EXISTS subs(
          id BIGSERIAL PRIMARY KEY,bid_id BIGINT NOT NULL REFERENCES bids(id) ON DELETE CASCADE,
          trade TEXT NOT NULL,name TEXT NOT NULL,email TEXT DEFAULT '',phone TEXT DEFAULT '',
          status TEXT DEFAULT 'Not Requested',sent_on DATE,created_at TIMESTAMPTZ DEFAULT now(),updated_at TIMESTAMPTZ DEFAULT now())""")
        c.execute("""CREATE TABLE IF NOT EXISTS history(
          id BIGSERIAL PRIMARY KEY,bid_id BIGINT,bid_number TEXT,action TEXT NOT NULL,details TEXT,
          created_at TIMESTAMPTZ DEFAULT now())""")

def auth(f):
    @wraps(f)
    def w(*a,**k):
        if not session.get("ok"):
            if request.path.startswith("/api/"): return jsonify(error="unauthorized"),401
            return redirect(url_for("login"))
        return f(*a,**k)
    return w

@app.before_request
def setup():
    if not getattr(app,"_db_ready",False):
        init_db(); app._db_ready=True

@app.route("/login",methods=["GET","POST"])
def login():
    err=""
    if request.method=="POST":
        if request.form.get("password","")==APP_PASSWORD:
            session.permanent=True; session["ok"]=True; return redirect("/")
        err="Incorrect password."
    return render_template("login.html",err=err)

@app.post("/logout")
def logout():
    session.clear(); return redirect("/login")

@app.get("/")
@auth
def home(): return render_template("index.html")

def hist(c,bid_id,action,details):
    b=c.execute("SELECT bid_number FROM bids WHERE id=%s",(bid_id,)).fetchone()
    c.execute("INSERT INTO history(bid_id,bid_number,action,details) VALUES(%s,%s,%s,%s)",
              (bid_id,b["bid_number"] if b else "",action,details))

def full_bid(c,b):
    d=dict(b); d["closing_date"]=str(d["closing_date"]); d["closing_time"]=str(d["closing_time"] or "")[:5]
    d["dollar_value"]=float(d["dollar_value"] or 0)
    ss=c.execute("SELECT * FROM subs WHERE bid_id=%s ORDER BY trade,name",(d["id"],)).fetchall()
    d["subs"]=[]
    for s in ss:
        x=dict(s); x["sent_on"]=str(x["sent_on"]) if x["sent_on"] else ""; d["subs"].append(x)
    return d

@app.get("/api/bids")
@auth
def bids():
    with db() as c: return jsonify([full_bid(c,x) for x in c.execute("SELECT * FROM bids ORDER BY closing_date,closing_time NULLS LAST").fetchall()])

@app.get("/api/bids/<int:i>")
@auth
def one(i):
    with db() as c:
        b=c.execute("SELECT * FROM bids WHERE id=%s",(i,)).fetchone()
        return jsonify(full_bid(c,b)) if b else (jsonify(error="not found"),404)

@app.post("/api/bids")
@auth
def add_bid():
    d=request.json or {}
    with db() as c:
        r=c.execute("""INSERT INTO bids(bid_number,project_name,closing_date,closing_time,client,address,notes)
        VALUES(%s,%s,%s,NULLIF(%s,'')::time,%s,%s,%s) RETURNING id""",
        (d.get("bid_number",""),d.get("project_name",""),d.get("closing_date"),d.get("closing_time",""),
         d.get("client",""),d.get("address",""),d.get("notes",""))).fetchone()
        hist(c,r["id"],"Bid created",f'{d.get("project_name","")} closes {d.get("closing_date","")}')
        return jsonify(id=r["id"]),201

@app.put("/api/bids/<int:i>")
@auth
def edit_bid(i):
    d=request.json or {}
    with db() as c:
        old=c.execute("SELECT * FROM bids WHERE id=%s",(i,)).fetchone()
        if not old:return jsonify(error="not found"),404
        vals={k:d.get(k,str(old[k] or "")) for k in ["bid_number","project_name","closing_date","closing_time","client","address","notes"]}
        c.execute("""UPDATE bids SET bid_number=%s,project_name=%s,closing_date=%s,closing_time=NULLIF(%s,'')::time,
        client=%s,address=%s,notes=%s,updated_at=now() WHERE id=%s""",
        (vals["bid_number"],vals["project_name"],vals["closing_date"],vals["closing_time"],vals["client"],vals["address"],vals["notes"],i))
        changes=[f"{k}: {old[k]} → {vals[k]}" for k in vals if str(old[k] or "")!=str(vals[k] or "")]
        hist(c,i,"Bid edited","; ".join(changes) or "Saved")
    return jsonify(ok=True)

@app.patch("/api/bids/<int:i>")
@auth
def patch_bid(i):
    d=request.json or {}
    with db() as c:
        old=c.execute("SELECT * FROM bids WHERE id=%s",(i,)).fetchone()
        if not old:return jsonify(error="not found"),404
        ch=[]
        if "status" in d:
            c.execute("UPDATE bids SET status=%s,updated_at=now() WHERE id=%s",(d["status"],i));ch.append(f'status: {old["status"]} → {d["status"]}')
        if "dollar_value" in d:
            v=float(d["dollar_value"] or 0);c.execute("UPDATE bids SET dollar_value=%s,updated_at=now() WHERE id=%s",(v,i));ch.append(f'dollar value: {old["dollar_value"]} → {v}')
        hist(c,i,"Bid updated","; ".join(ch))
    return jsonify(ok=True)

@app.post("/api/bids/<int:i>/subs")
@auth
def add_sub(i):
    d=request.json or {}
    with db() as c:
        r=c.execute("INSERT INTO subs(bid_id,trade,name,email,phone) VALUES(%s,%s,%s,%s,%s) RETURNING id",
        (i,d.get("trade",""),d.get("name",""),d.get("email",""),d.get("phone",""))).fetchone()
        hist(c,i,"Subcontractor added",f'{d.get("trade","")} — {d.get("name","")}')
        return jsonify(id=r["id"]),201

@app.patch("/api/subs/<int:i>")
@auth
def patch_sub(i):
    d=request.json or {}
    with db() as c:
        s=c.execute("SELECT * FROM subs WHERE id=%s",(i,)).fetchone()
        if not s:return jsonify(error="not found"),404
        ch=[]
        if "status" in d:
            c.execute("UPDATE subs SET status=%s,updated_at=now() WHERE id=%s",(d["status"],i));ch.append(f'status: {s["status"]} → {d["status"]}')
        if "sent_on" in d:
            val=d["sent_on"] or None
            c.execute("UPDATE subs SET sent_on=%s,updated_at=now() WHERE id=%s",(val,i))
            if val and s["status"]=="Not Requested": c.execute("UPDATE subs SET status='Request Sent' WHERE id=%s",(i,))
            ch.append(f'sent on: {s["sent_on"] or ""} → {val or ""}')
        hist(c,s["bid_id"],"Subtrade updated",f'{s["trade"]} / {s["name"]}: '+"; ".join(ch))
    return jsonify(ok=True)

@app.delete("/api/subs/<int:i>")
@auth
def del_sub(i):
    with db() as c:
        s=c.execute("SELECT * FROM subs WHERE id=%s",(i,)).fetchone()
        if s:
            hist(c,s["bid_id"],"Subcontractor removed",f'{s["trade"]} — {s["name"]}')
            c.execute("DELETE FROM subs WHERE id=%s",(i,))
    return "",204


@app.delete("/api/bids/<int:i>")
@auth
def del_bid(i):
    with db() as c:
        b=c.execute("SELECT * FROM bids WHERE id=%s",(i,)).fetchone()
        if not b: return jsonify(error="not found"),404
        c.execute("INSERT INTO history(bid_id,bid_number,action,details) VALUES(NULL,%s,%s,%s)",
                  (b["bid_number"],"Job deleted",f'{b["project_name"]} was permanently deleted'))
        c.execute("DELETE FROM bids WHERE id=%s",(i,))
    return "",204

@app.get("/api/history")
@auth
def history():
    bn=request.args.get("bid_number","")
    with db() as c:
        rows=c.execute("""SELECT * FROM history WHERE (%s='' OR bid_number ILIKE %s) ORDER BY id DESC LIMIT 1000""",(bn,f"%{bn}%")).fetchall()
        return jsonify(rows)
