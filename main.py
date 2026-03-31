"""
ArtCraft Backend — FastAPI + MongoDB (PyMongo) + Stripe
"""

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import hashlib, uuid, os, stripe
from datetime import datetime
from typing import Optional
from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv

load_dotenv()

# ── APP ───────────────────────────────────────────────────────
app = FastAPI(title="ArtCraft API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# ── MONGODB ───────────────────────────────────────────────────
MONGO_URL    = os.getenv("MONGO_URL", "mongodb://localhost:27017")
client       = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000, tls=True, tlsAllowInvalidCertificates=True)
db           = client["artcraft"]

users_col     = db["users"]
artworks_col  = db["artworks"]
tutorials_col = db["tutorials"]
orders_col    = db["orders"]
payments_col  = db["payments"]
jobs_col      = db["jobs"]
messages_col  = db["messages"]
notifs_col    = db["notifications"]

# ── STRIPE ────────────────────────────────────────────────────
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
FRONTEND_URL   = os.getenv("FRONTEND_URL", "http://127.0.0.1:5500")

# ── HELPERS ───────────────────────────────────────────────────
def hash_password(p: str) -> str:
    return hashlib.sha256(p.encode()).hexdigest()

def make_token(user_id: str) -> str:
    return hashlib.sha256(f"{user_id}{uuid.uuid4()}".encode()).hexdigest()

def to_str_id(doc: dict) -> dict:
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc

def get_current_user(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = auth[7:]
    user = users_col.find_one({"session_token": token})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user

def save_upload(file: UploadFile) -> str:
    ext      = os.path.splitext(file.filename)[1] if file.filename else ""
    filename = f"{uuid.uuid4()}{ext}"
    filepath = os.path.join("uploads", filename)
    with open(filepath, "wb") as f:
        f.write(file.file.read())
    return filepath

def push_notification(user_id: str, text: str):
    notifs_col.insert_one({
        "user_id":    user_id,
        "text":       text,
        "read":       False,
        "created_at": datetime.utcnow().isoformat(),
    })

# ═══════════════════════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════════════════════

@app.post("/auth/signup")
def signup(
    first_name: str = Form(...),
    last_name:  str = Form(...),
    email:      str = Form(...),
    password:   str = Form(...),
    role:       str = Form(...)
):
    email = email.lower().strip()
    if users_col.find_one({"email": email, "role": role}):
        raise HTTPException(400, "Account already exists for this email + role")

    user = {
        "first_name": first_name, "last_name": last_name,
        "email": email, "password_hash": hash_password(password),
        "role": role, "session_token": None,
        "avatar_url": None, "cover_url": None,
        "created_at": datetime.utcnow().isoformat(),
        "medium": "", "city": "", "bio": "", "skills": [],
        "instagram": "", "website": "",
        "brand_name": "", "industry": "",
        "phone": "", "upi": "", "bank_account": "", "ifsc": "",
    }
    result = users_col.insert_one(user)
    token  = make_token(str(result.inserted_id))
    users_col.update_one({"_id": result.inserted_id}, {"$set": {"session_token": token}})
    return {"token": token, "user_id": str(result.inserted_id),
            "role": role, "name": f"{first_name} {last_name}", "email": email}


@app.post("/auth/login")
def login(email: str = Form(...), password: str = Form(...), role: str = Form(...)):
    email = email.lower().strip()
    user  = users_col.find_one({"email": email, "role": role})
    if not user or user["password_hash"] != hash_password(password):
        raise HTTPException(401, "Incorrect email, password, or role")
    token = make_token(str(user["_id"]))
    users_col.update_one({"_id": user["_id"]}, {"$set": {"session_token": token}})
    return {"token": token, "user_id": str(user["_id"]),
            "role": user["role"], "name": f"{user['first_name']} {user['last_name']}",
            "email": user["email"]}


@app.post("/auth/logout")
def logout(current_user=Depends(get_current_user)):
    users_col.update_one({"_id": current_user["_id"]}, {"$set": {"session_token": None}})
    return {"message": "Logged out"}


@app.get("/auth/me")
def get_me(current_user=Depends(get_current_user)):
    return to_str_id({**current_user, "password_hash": "[hidden]"})


# ═══════════════════════════════════════════════════════════════
# PROFILE
# ═══════════════════════════════════════════════════════════════

@app.put("/profile")
def update_profile(
    first_name: Optional[str] = Form(None), last_name: Optional[str] = Form(None),
    medium: Optional[str] = Form(None),     city: Optional[str] = Form(None),
    bio: Optional[str] = Form(None),        instagram: Optional[str] = Form(None),
    website: Optional[str] = Form(None),    brand_name: Optional[str] = Form(None),
    industry: Optional[str] = Form(None),   phone: Optional[str] = Form(None),
    upi: Optional[str] = Form(None),        bank_account: Optional[str] = Form(None),
    ifsc: Optional[str] = Form(None),
    avatar: Optional[UploadFile] = File(None),
    cover:  Optional[UploadFile] = File(None),
    current_user=Depends(get_current_user)
):
    update = {}
    for k, v in {"first_name": first_name, "last_name": last_name, "medium": medium,
                 "city": city, "bio": bio, "instagram": instagram, "website": website,
                 "brand_name": brand_name, "industry": industry, "phone": phone,
                 "upi": upi, "bank_account": bank_account, "ifsc": ifsc}.items():
        if v is not None:
            update[k] = v
    if avatar:
        update["avatar_url"] = f"/{save_upload(avatar)}"
    if cover:
        update["cover_url"] = f"/{save_upload(cover)}"
    if update:
        users_col.update_one({"_id": current_user["_id"]}, {"$set": update})
    updated = users_col.find_one({"_id": current_user["_id"]})
    return to_str_id({**updated, "password_hash": "[hidden]"})


@app.post("/profile/skills")
def add_skill(skill: str = Form(...), current_user=Depends(get_current_user)):
    users_col.update_one({"_id": current_user["_id"]}, {"$addToSet": {"skills": skill}})
    return {"message": "Skill added"}


@app.delete("/profile/skills/{skill}")
def remove_skill(skill: str, current_user=Depends(get_current_user)):
    users_col.update_one({"_id": current_user["_id"]}, {"$pull": {"skills": skill}})
    return {"message": "Skill removed"}


# ═══════════════════════════════════════════════════════════════
# ARTWORKS
# ═══════════════════════════════════════════════════════════════

@app.post("/artworks")
def create_artwork(
    title: str = Form(...), price: float = Form(...),
    medium: str = Form("Other"), dims: str = Form(""),
    desc: str = Form(""), status: str = Form("draft"),
    image: Optional[UploadFile] = File(None),
    current_user=Depends(get_current_user)
):
    if current_user["role"] != "artist":
        raise HTTPException(403, "Only artists can upload artworks")
    image_url = f"/{save_upload(image)}" if image else None
    artwork = {
        "artist_id": str(current_user["_id"]),
        "artist_name": f"{current_user['first_name']} {current_user['last_name']}",
        "artist_avatar": current_user.get("avatar_url"),
        "title": title, "price": price, "medium": medium,
        "dims": dims, "desc": desc, "status": status,
        "image_url": image_url,
        "created_at": datetime.utcnow().isoformat(),
    }
    result = artworks_col.insert_one(artwork)
    artwork["_id"] = str(result.inserted_id)
    return artwork


@app.get("/artworks")
def list_artworks(status: Optional[str] = None, medium: Optional[str] = None,
                  artist_id: Optional[str] = None, search: Optional[str] = None):
    query = {}
    query["status"] = status if status else "listed"
    if medium:    query["medium"] = medium
    if artist_id: query["artist_id"] = artist_id
    if search:
        query["$or"] = [
            {"title":       {"$regex": search, "$options": "i"}},
            {"artist_name": {"$regex": search, "$options": "i"}},
            {"medium":      {"$regex": search, "$options": "i"}},
        ]
    return [to_str_id(a) for a in artworks_col.find(query).sort("created_at", -1)]


@app.get("/artworks/mine")
def my_artworks(current_user=Depends(get_current_user)):
    return [to_str_id(a) for a in
            artworks_col.find({"artist_id": str(current_user["_id"])}).sort("created_at", -1)]


@app.get("/artworks/{artwork_id}")
def get_artwork(artwork_id: str):
    try:
        art = artworks_col.find_one({"_id": ObjectId(artwork_id)})
    except Exception:
        raise HTTPException(404, "Artwork not found")
    if not art:
        raise HTTPException(404, "Artwork not found")
    return to_str_id(art)


@app.put("/artworks/{artwork_id}")
def update_artwork(
    artwork_id: str,
    title: Optional[str] = Form(None), price: Optional[float] = Form(None),
    medium: Optional[str] = Form(None), dims: Optional[str] = Form(None),
    desc: Optional[str] = Form(None),   status: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    current_user=Depends(get_current_user)
):
    try:
        art = artworks_col.find_one({"_id": ObjectId(artwork_id)})
    except Exception:
        raise HTTPException(404, "Not found")
    if not art or art["artist_id"] != str(current_user["_id"]):
        raise HTTPException(403, "Not your artwork")
    update = {}
    for k, v in {"title": title, "price": price, "medium": medium,
                 "dims": dims, "desc": desc, "status": status}.items():
        if v is not None: update[k] = v
    if image:
        update["image_url"] = f"/{save_upload(image)}"
    if update:
        artworks_col.update_one({"_id": ObjectId(artwork_id)}, {"$set": update})
    return to_str_id(artworks_col.find_one({"_id": ObjectId(artwork_id)}))


@app.delete("/artworks/{artwork_id}")
def delete_artwork(artwork_id: str, current_user=Depends(get_current_user)):
    try:
        art = artworks_col.find_one({"_id": ObjectId(artwork_id)})
    except Exception:
        raise HTTPException(404, "Not found")
    if not art or art["artist_id"] != str(current_user["_id"]):
        raise HTTPException(403, "Not your artwork")
    artworks_col.delete_one({"_id": ObjectId(artwork_id)})
    return {"message": "Deleted"}


# ═══════════════════════════════════════════════════════════════
# TUTORIALS
# ═══════════════════════════════════════════════════════════════

@app.post("/tutorials")
def create_tutorial(
    title: str = Form(...), price: float = Form(...),
    duration: str = Form(""), level: str = Form("Beginner"),
    lang: str = Form("English"), desc: str = Form(""),
    video: Optional[UploadFile] = File(None),
    thumb: Optional[UploadFile] = File(None),
    current_user=Depends(get_current_user)
):
    if current_user["role"] != "artist":
        raise HTTPException(403, "Only artists can create tutorials")
    tutorial = {
        "artist_id": str(current_user["_id"]),
        "artist_name": f"{current_user['first_name']} {current_user['last_name']}",
        "artist_avatar": current_user.get("avatar_url"),
        "title": title, "price": price, "duration": duration,
        "level": level, "lang": lang, "desc": desc,
        "video_url": f"/{save_upload(video)}" if video else None,
        "thumb_url": f"/{save_upload(thumb)}" if thumb else None,
        "students": 0, "earnings": 0.0,
        "created_at": datetime.utcnow().isoformat(),
    }
    result = tutorials_col.insert_one(tutorial)
    tutorial["_id"] = str(result.inserted_id)
    return tutorial


@app.get("/tutorials")
def list_tutorials(artist_id: Optional[str] = None):
    query = {}
    if artist_id: query["artist_id"] = artist_id
    tuts = []
    for t in tutorials_col.find(query).sort("created_at", -1):
        t = to_str_id(t)
        t.pop("video_url", None)
        tuts.append(t)
    return tuts


@app.get("/tutorials/mine/purchased")
def my_purchased_tutorials(current_user=Depends(get_current_user)):
    paid = payments_col.find({
        "user_id": str(current_user["_id"]),
        "status": "completed", "type": "tutorial"
    })
    tuts = []
    for p in paid:
        try:
            tut = tutorials_col.find_one({"_id": ObjectId(p["tutorial_id"])})
            if tut: tuts.append(to_str_id(tut))
        except Exception:
            pass
    return tuts


@app.get("/tutorials/{tutorial_id}")
def get_tutorial(tutorial_id: str, request: Request):
    try:
        tut = tutorials_col.find_one({"_id": ObjectId(tutorial_id)})
    except Exception:
        raise HTTPException(404, "Not found")
    if not tut:
        raise HTTPException(404, "Not found")
    tut = to_str_id(tut)

    auth = request.headers.get("Authorization", "")
    current_user = None
    if auth.startswith("Bearer "):
        current_user = users_col.find_one({"session_token": auth[7:]})

    user_id    = str(current_user["_id"]) if current_user else None
    is_owner   = user_id and user_id == tut["artist_id"]
    has_bought = bool(payments_col.find_one({
        "user_id": user_id, "tutorial_id": tutorial_id, "status": "completed"
    })) if user_id else False

    if not is_owner and not has_bought:
        tut.pop("video_url", None)
        tut["locked"] = True
    else:
        tut["locked"] = False
    return tut


@app.delete("/tutorials/{tutorial_id}")
def delete_tutorial(tutorial_id: str, current_user=Depends(get_current_user)):
    try:
        tut = tutorials_col.find_one({"_id": ObjectId(tutorial_id)})
    except Exception:
        raise HTTPException(404, "Not found")
    if not tut or tut["artist_id"] != str(current_user["_id"]):
        raise HTTPException(403, "Not your tutorial")
    tutorials_col.delete_one({"_id": ObjectId(tutorial_id)})
    return {"message": "Deleted"}


# ═══════════════════════════════════════════════════════════════
# PAYMENTS — TUTORIAL
# ═══════════════════════════════════════════════════════════════

@app.post("/payments/tutorial/checkout")
def tutorial_checkout(tutorial_id: str = Form(...), current_user=Depends(get_current_user)):
    try:
        tut = tutorials_col.find_one({"_id": ObjectId(tutorial_id)})
    except Exception:
        raise HTTPException(404, "Tutorial not found")
    if not tut:
        raise HTTPException(404, "Tutorial not found")
    if payments_col.find_one({"user_id": str(current_user["_id"]),
                               "tutorial_id": tutorial_id, "status": "completed"}):
        raise HTTPException(400, "Already purchased")

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{"price_data": {"currency": "inr",
                                    "unit_amount": int(float(tut["price"]) * 100),
                                    "product_data": {"name": tut["title"],
                                                     "description": f"Tutorial by {tut['artist_name']}"}},
                     "quantity": 1}],
        mode="payment",
        success_url=f"{FRONTEND_URL}/customer.html?session_id={{CHECKOUT_SESSION_ID}}&type=tutorial&id={tutorial_id}",
        cancel_url=f"{FRONTEND_URL}/customer.html",
        metadata={"tutorial_id": tutorial_id, "user_id": str(current_user["_id"]), "type": "tutorial"}
    )
    payments_col.insert_one({
        "user_id": str(current_user["_id"]), "tutorial_id": tutorial_id,
        "type": "tutorial", "amount": float(tut["price"]),
        "stripe_session_id": session.id, "status": "pending",
        "created_at": datetime.utcnow().isoformat(),
    })
    return {"checkout_url": session.url, "session_id": session.id}


@app.post("/payments/tutorial/verify")
def verify_tutorial(session_id: str = Form(...), current_user=Depends(get_current_user)):
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except stripe.error.StripeError as e:
        raise HTTPException(400, str(e))
    if session.payment_status != "paid":
        raise HTTPException(400, "Payment not completed")

    tutorial_id = session.metadata.get("tutorial_id")
    payments_col.update_one({"stripe_session_id": session_id},
                             {"$set": {"status": "completed", "paid_at": datetime.utcnow().isoformat()}})
    try:
        tut = tutorials_col.find_one({"_id": ObjectId(tutorial_id)})
        if tut:
            tutorials_col.update_one({"_id": ObjectId(tutorial_id)},
                                     {"$inc": {"students": 1, "earnings": float(tut["price"])}})
            buyer_name = f"{current_user['first_name']} {current_user['last_name']}"
            push_notification(tut["artist_id"],
                f"🎬 {buyer_name} purchased your tutorial '{tut['title']}' — ₹{tut['price']} earned!")
    except Exception:
        pass
    return {"message": "Payment verified", "tutorial_id": tutorial_id}


# ═══════════════════════════════════════════════════════════════
# PAYMENTS — ARTWORK (New flow: order → approve → pay)
# ═══════════════════════════════════════════════════════════════

@app.post("/payments/artwork/checkout")
def create_artwork_order(
    artwork_id: str = Form(...), address: str = Form(...),
    phone: str = Form(...), note: str = Form(""),
    payment_type: str = Form("online"),
    current_user=Depends(get_current_user)
):
    """Step 1: Customer places order — NO payment yet. Artist must approve first."""
    try:
        art = artworks_col.find_one({"_id": ObjectId(artwork_id)})
    except Exception:
        raise HTTPException(404, "Artwork not found")
    if not art:
        raise HTTPException(404, "Artwork not found")
    if art["status"] != "listed":
        raise HTTPException(400, "Artwork not available for purchase")

    order = {
        "artwork_id": artwork_id, "art_title": art["title"],
        "art_image_url": art.get("image_url"),
        "artist_id": art["artist_id"], "artist_name": art["artist_name"],
        "buyer_id": str(current_user["_id"]),
        "buyer_name": f"{current_user['first_name']} {current_user['last_name']}",
        "buyer_email": current_user["email"],
        "address": address, "phone": phone, "note": note,
        "amount": float(art["price"]),
        "payment_type": payment_type,
        "status": "pending",
        "payment_status": "unpaid",
        "created_at": datetime.utcnow().isoformat(),
    }
    result = orders_col.insert_one(order)
    push_notification(art["artist_id"],
        f"🛒 New order from {order['buyer_name']} for '{art['title']}' — ₹{art['price']}. Please approve or reject.")
    return {"order_id": str(result.inserted_id), "message": "Order sent to artist for approval"}


@app.post("/payments/artwork/verify")
def verify_artwork_payment(session_id: str = Form(...), current_user=Depends(get_current_user)):
    """Step 3: After customer pays on Stripe — mark order as paid."""
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except stripe.error.StripeError as e:
        raise HTTPException(400, str(e))
    if session.payment_status != "paid":
        raise HTTPException(400, "Payment not completed")

    orders_col.update_one({"stripe_session_id": session_id},
                           {"$set": {"payment_status": "paid",
                                     "paid_at": datetime.utcnow().isoformat()}})
    try:
        order = orders_col.find_one({"stripe_session_id": session_id})
        if order:
            push_notification(order["artist_id"],
                f"💰 Payment of ₹{int(order['amount'])} received from {order['buyer_name']} "
                f"for '{order['art_title']}'. Please ship now!")
            push_notification(order["buyer_id"],
                f"✅ Payment confirmed for '{order['art_title']}'. Artist will ship soon!")
    except Exception:
        pass
    return {"message": "Payment verified"}


# ═══════════════════════════════════════════════════════════════
# ORDERS
# ═══════════════════════════════════════════════════════════════

@app.get("/orders/mine")
def my_orders(current_user=Depends(get_current_user)):
    return [to_str_id(o) for o in
            orders_col.find({"buyer_id": str(current_user["_id"])}).sort("created_at", -1)]


@app.get("/orders/artist")
def artist_orders(current_user=Depends(get_current_user)):
    if current_user["role"] != "artist":
        raise HTTPException(403, "Artists only")
    return [to_str_id(o) for o in
            orders_col.find({"artist_id": str(current_user["_id"])}).sort("created_at", -1)]


@app.put("/orders/{order_id}/status")
def update_order_status(
    order_id: str, status: str = Form(...),
    current_user=Depends(get_current_user)
):
    try:
        order = orders_col.find_one({"_id": ObjectId(order_id)})
    except Exception:
        raise HTTPException(404, "Not found")
    if not order:
        raise HTTPException(404, "Order not found")
    if current_user["role"] == "artist" and order["artist_id"] != str(current_user["_id"]):
        raise HTTPException(403, "Not your order")
    if current_user["role"] == "customer" and order["buyer_id"] != str(current_user["_id"]):
        raise HTTPException(403, "Not your order")

    orders_col.update_one({"_id": ObjectId(order_id)}, {"$set": {"status": status}})

    # Step 2: On approval — create Stripe payment link for customer
    if status == "approved":
        if order.get("payment_type") == "cod":
            orders_col.update_one({"_id": ObjectId(order_id)},
                                   {"$set": {"payment_status": "cod_pending"}})
            push_notification(order["buyer_id"],
                f"✅ Order for '{order['art_title']}' approved! Pay ₹{int(order['amount'])} cash on delivery.")
        else:
            try:
                stripe_session = stripe.checkout.Session.create(
                    payment_method_types=["card"],
                    line_items=[{"price_data": {
                        "currency": "inr",
                        "unit_amount": int(float(order["amount"]) * 100),
                        "product_data": {"name": order.get("art_title", "Artwork"),
                                         "description": f"By {order.get('artist_name', 'Artist')}"}},
                        "quantity": 1}],
                    mode="payment",
                    success_url=(f"{FRONTEND_URL}/customer.html"
                                 f"?session_id={{CHECKOUT_SESSION_ID}}&type=artwork"
                                 f"&id={order.get('artwork_id', '')}"),
                    cancel_url=f"{FRONTEND_URL}/customer.html",
                    metadata={"order_id": order_id, "artwork_id": order.get("artwork_id", ""),
                              "user_id": order["buyer_id"], "type": "artwork"},
                    customer_email=order.get("buyer_email"),
                )
                orders_col.update_one({"_id": ObjectId(order_id)}, {"$set": {
                    "stripe_session_id": stripe_session.id,
                    "payment_checkout_url": stripe_session.url,
                    "payment_status": "awaiting_payment",
                }})
                push_notification(order["buyer_id"],
                    f"✅ Artist approved your order for '{order['art_title']}'! "
                    f"Complete payment of ₹{int(order['amount'])} — check My Orders → Pay Now.")
            except Exception as e:
                push_notification(order["buyer_id"],
                    f"✅ Artist approved your order for '{order['art_title']}'! Go to My Orders to pay.")

    elif status == "rejected":
        push_notification(order["buyer_id"],
            f"❌ Your order for '{order['art_title']}' was not accepted. No payment was taken.")

    elif status == "shipped":
        push_notification(order["buyer_id"],
            f"📦 Your order '{order['art_title']}' has been shipped!")

    elif status == "delivered":
        push_notification(order["artist_id"],
            f"🎉 Order '{order['art_title']}' marked as delivered!")

    return {"message": f"Order {status}"}


# ═══════════════════════════════════════════════════════════════
# JOBS
# ═══════════════════════════════════════════════════════════════

@app.post("/jobs")
def create_job(
    title: str = Form(...), budget: str = Form(...),
    job_type: str = Form("Freelance"), location: str = Form("Remote"),
    dept: str = Form(""), deadline: str = Form(""),
    skills: str = Form(""), desc: str = Form(""),
    status: str = Form("active"),
    current_user=Depends(get_current_user)
):
    if current_user["role"] != "brand":
        raise HTTPException(403, "Brands only")
    job = {
        "brand_id":   str(current_user["_id"]),
        "brand_name": current_user.get("brand_name") or f"{current_user['first_name']} {current_user['last_name']}",
        "title": title, "budget": budget, "job_type": job_type,
        "location": location, "dept": dept, "deadline": deadline,
        "skills": [s.strip() for s in skills.split(",") if s.strip()],
        "desc": desc, "status": status,
        "created_at": datetime.utcnow().isoformat(),
    }
    result = jobs_col.insert_one(job)
    job["_id"] = str(result.inserted_id)
    return job


@app.get("/jobs")
def list_jobs(status: Optional[str] = "active"):
    query = {"status": status} if status else {}
    return [to_str_id(j) for j in jobs_col.find(query).sort("created_at", -1)]


@app.get("/jobs/applications")
def get_applications(current_user=Depends(get_current_user)):
    uid = str(current_user["_id"])
    query = {"brand_id": uid} if current_user["role"] == "brand" else {"artist_id": uid}
    return [to_str_id(a) for a in db["applications"].find(query).sort("applied_at", -1)]


@app.get("/jobs/{job_id}/applications")
def get_job_applications(job_id: str, current_user=Depends(get_current_user)):
    if current_user["role"] != "brand":
        raise HTTPException(403, "Brands only")
    return [to_str_id(a) for a in db["applications"].find({"job_id": job_id})]


@app.post("/jobs/{job_id}/apply")
def apply_to_job(job_id: str, message: str = Form(""), current_user=Depends(get_current_user)):
    if current_user["role"] != "artist":
        raise HTTPException(403, "Artists only")
    try:
        job = jobs_col.find_one({"_id": ObjectId(job_id)})
    except Exception:
        raise HTTPException(404, "Job not found")
    if not job:
        raise HTTPException(404, "Job not found")
    if db["applications"].find_one({"job_id": job_id, "artist_id": str(current_user["_id"])}):
        raise HTTPException(400, "Already applied")
    app_doc = {
        "job_id": job_id, "job_title": job["title"], "brand_id": job["brand_id"],
        "artist_id": str(current_user["_id"]),
        "artist_name": f"{current_user['first_name']} {current_user['last_name']}",
        "artist_avatar": current_user.get("avatar_url"),
        "skills": current_user.get("skills", []),
        "city": current_user.get("city", ""),
        "medium": current_user.get("medium", ""),
        "message": message, "status": "pending",
        "applied_at": datetime.utcnow().isoformat(),
    }
    db["applications"].insert_one(app_doc)
    push_notification(job["brand_id"],
        f"🎨 New application from {app_doc['artist_name']} for '{job['title']}'")
    return {"message": "Application sent"}


@app.put("/jobs/applications/{app_id}/status")
def update_app_status(app_id: str, status: str = Form(...), current_user=Depends(get_current_user)):
    if current_user["role"] != "brand":
        raise HTTPException(403, "Brands only")
    try:
        db["applications"].update_one({"_id": ObjectId(app_id)}, {"$set": {"status": status}})
    except Exception:
        raise HTTPException(404, "Application not found")
    return {"message": f"Status updated to {status}"}


@app.delete("/jobs/{job_id}")
def delete_job(job_id: str, current_user=Depends(get_current_user)):
    if current_user["role"] != "brand":
        raise HTTPException(403, "Brands only")
    try:
        jobs_col.delete_one({"_id": ObjectId(job_id)})
        db["applications"].delete_many({"job_id": job_id})
    except Exception:
        raise HTTPException(404, "Job not found")
    return {"message": "Deleted"}


# ═══════════════════════════════════════════════════════════════
# COMPETITIONS
# ═══════════════════════════════════════════════════════════════

@app.post("/competitions")
def create_competition(
    title: str = Form(...), prize: str = Form(...),
    category: str = Form("Other"), start_date: str = Form(""),
    end_date: str = Form(""), desc: str = Form(""), tags: str = Form(""),
    current_user=Depends(get_current_user)
):
    if current_user["role"] != "brand":
        raise HTTPException(403, "Brands only")
    comp = {
        "brand_id":   str(current_user["_id"]),
        "brand_name": current_user.get("brand_name") or f"{current_user['first_name']} {current_user['last_name']}",
        "title": title, "prize": prize, "category": category,
        "start_date": start_date, "end_date": end_date, "desc": desc,
        "tags": [t.strip() for t in tags.split(",") if t.strip()],
        "entries": 0, "status": "active",
        "created_at": datetime.utcnow().isoformat(),
    }
    result = db["competitions"].insert_one(comp)
    comp["_id"] = str(result.inserted_id)
    return comp


@app.get("/competitions")
def list_competitions(status: Optional[str] = "active", brand_id: Optional[str] = None):
    query = {}
    if status: query["status"] = status
    if brand_id: query["brand_id"] = brand_id
    return [to_str_id(c) for c in db["competitions"].find(query).sort("created_at", -1)]


@app.get("/competitions/mine/registered")
def my_registered_competitions(current_user=Depends(get_current_user)):
    regs = db["comp_registrations"].find({"artist_id": str(current_user["_id"])})
    return [{"comp_id": r["comp_id"]} for r in regs]


@app.get("/competitions/{comp_id}/registrations")
def get_competition_registrations(comp_id: str, current_user=Depends(get_current_user)):
    regs = list(db["comp_registrations"].find({"comp_id": comp_id}))
    return [{"artist_id": r.get("artist_id"), "artist_name": r.get("artist_name"),
             "registered_at": r.get("registered_at")} for r in regs]


@app.post("/competitions/{comp_id}/register")
def register_competition(comp_id: str, current_user=Depends(get_current_user)):
    if current_user["role"] != "artist":
        raise HTTPException(403, "Artists only")
    if db["comp_registrations"].find_one({"comp_id": comp_id, "artist_id": str(current_user["_id"])}):
        raise HTTPException(400, "Already registered")
    db["comp_registrations"].insert_one({
        "comp_id": comp_id, "artist_id": str(current_user["_id"]),
        "artist_name": f"{current_user['first_name']} {current_user['last_name']}",
        "registered_at": datetime.utcnow().isoformat(),
    })
    try:
        db["competitions"].update_one({"_id": ObjectId(comp_id)}, {"$inc": {"entries": 1}})
        comp_doc = db["competitions"].find_one({"_id": ObjectId(comp_id)})
        if comp_doc:
            push_notification(comp_doc["brand_id"],
                f"🏆 {current_user['first_name']} {current_user['last_name']} registered for '{comp_doc['title']}'")
    except Exception:
        pass
    return {"message": "Registered"}


# ═══════════════════════════════════════════════════════════════
# MESSAGES
# ═══════════════════════════════════════════════════════════════

@app.post("/messages/send")
def send_message(recipient_id: str = Form(...), body: str = Form(...),
                 current_user=Depends(get_current_user)):
    sender_id = str(current_user["_id"])
    thread_id = "_".join(sorted([sender_id, recipient_id]))
    messages_col.insert_one({
        "thread_id": thread_id, "from_id": sender_id, "to_id": recipient_id,
        "from_name": f"{current_user['first_name']} {current_user['last_name']}",
        "body": body, "read": False,
        "created_at": datetime.utcnow().isoformat(),
    })
    return {"message": "Sent", "thread_id": thread_id}


@app.get("/messages/threads")
def my_threads(current_user=Depends(get_current_user)):
    user_id = str(current_user["_id"])
    msgs = list(messages_col.find(
        {"$or": [{"from_id": user_id}, {"to_id": user_id}]}
    ).sort("created_at", -1))
    threads = {}
    for m in msgs:
        tid = m["thread_id"]
        if tid not in threads:
            other_id = m["to_id"] if m["from_id"] == user_id else m["from_id"]
            other = users_col.find_one({"_id": ObjectId(other_id)}) if other_id else None
            threads[tid] = {
                "thread_id": tid,
                "other_user": {
                    "id": other_id,
                    "name": f"{other['first_name']} {other['last_name']}" if other else "Unknown",
                    "avatar_url": other.get("avatar_url") if other else None,
                    "role": other.get("role") if other else "",
                } if other else {},
                "last_message": to_str_id(m),
                "unread_count": 0,
            }
        if m["to_id"] == user_id and not m["read"]:
            threads[tid]["unread_count"] += 1
    return list(threads.values())


@app.get("/messages/thread/{thread_id}")
def get_thread(thread_id: str, current_user=Depends(get_current_user)):
    user_id = str(current_user["_id"])
    if user_id not in thread_id.split("_"):
        raise HTTPException(403, "Not your thread")
    msgs = [to_str_id(m) for m in
            messages_col.find({"thread_id": thread_id}).sort("created_at", 1)]
    messages_col.update_many(
        {"thread_id": thread_id, "to_id": user_id, "read": False},
        {"$set": {"read": True}}
    )
    return msgs


# ═══════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════

@app.get("/notifications")
def get_notifications(current_user=Depends(get_current_user)):
    return [to_str_id(n) for n in
            notifs_col.find({"user_id": str(current_user["_id"])}).sort("created_at", -1).limit(50)]


@app.put("/notifications/read-all")
def mark_all_read(current_user=Depends(get_current_user)):
    notifs_col.update_many({"user_id": str(current_user["_id"]), "read": False},
                            {"$set": {"read": True}})
    return {"message": "All marked as read"}


# ═══════════════════════════════════════════════════════════════
# ARTISTS DIRECTORY
# ═══════════════════════════════════════════════════════════════

@app.get("/artists")
def search_artists(search: Optional[str] = None, medium: Optional[str] = None,
                   city: Optional[str] = None):
    query: dict = {"role": "artist"}
    if medium: query["medium"] = {"$regex": medium, "$options": "i"}
    if city:   query["city"]   = {"$regex": city,   "$options": "i"}
    if search:
        query["$or"] = [
            {"first_name": {"$regex": search, "$options": "i"}},
            {"last_name":  {"$regex": search, "$options": "i"}},
            {"medium":     {"$regex": search, "$options": "i"}},
            {"city":       {"$regex": search, "$options": "i"}},
        ]
    artists = []
    for u in users_col.find(query):
        u = to_str_id(u)
        u.pop("password_hash", None)
        u.pop("session_token", None)
        u["listed_artworks"] = artworks_col.count_documents(
            {"artist_id": u["_id"], "status": "listed"})
        artists.append(u)
    return artists


@app.get("/artists/{artist_id}")
def get_artist_profile(artist_id: str):
    try:
        user = users_col.find_one({"_id": ObjectId(artist_id), "role": "artist"})
    except Exception:
        raise HTTPException(404, "Not found")
    if not user:
        raise HTTPException(404, "Artist not found")
    user = to_str_id(user)
    user.pop("password_hash", None)
    user.pop("session_token", None)
    user["artworks"] = [to_str_id(a) for a in
                        artworks_col.find({"artist_id": artist_id, "status": "listed"})]
    tuts = []
    for t in tutorials_col.find({"artist_id": artist_id}):
        t = to_str_id(t)
        t.pop("video_url", None)
        tuts.append(t)
    user["tutorials"] = tuts
    return user


# ═══════════════════════════════════════════════════════════════
# BRAND → ARTIST PAYMENTS
# ═══════════════════════════════════════════════════════════════

@app.post("/payments/brand/pay-artist")
def brand_pay_artist(
    artist_id: str = Form(...), amount: float = Form(...),
    desc: str = Form("Job Payment"), notes: str = Form(""),
    current_user=Depends(get_current_user)
):
    if current_user["role"] != "brand":
        raise HTTPException(403, "Brands only")
    try:
        artist = users_col.find_one({"_id": ObjectId(artist_id), "role": "artist"})
    except Exception:
        raise HTTPException(404, "Artist not found")
    if not artist:
        raise HTTPException(404, "Artist not found")

    artist_name = f"{artist['first_name']} {artist['last_name']}"
    brand_name  = current_user.get("brand_name") or f"{current_user['first_name']} {current_user['last_name']}"
    amount_paise = int(float(amount))

    intent = stripe.PaymentIntent.create(
        amount=amount_paise, currency="inr",
        description=f"{desc} — {artist_name} (ArtCraft)",
        payment_method_types=["card"],
        metadata={"brand_id": str(current_user["_id"]), "artist_id": artist_id,
                  "artist_name": artist_name, "desc": desc, "type": "brand_payment"}
    )
    payments_col.insert_one({
        "brand_id": str(current_user["_id"]), "brand_name": brand_name,
        "artist_id": artist_id, "artist_name": artist_name,
        "amount": amount_paise, "desc": desc, "notes": notes,
        "stripe_pi_id": intent.id, "client_secret": intent.client_secret,
        "type": "brand_payment", "status": "pending",
        "created_at": datetime.utcnow().isoformat(),
    })
    return {"client_secret": intent.client_secret,
            "payment_intent_id": intent.id,
            "amount_paise": amount_paise, "artist_name": artist_name}


@app.post("/payments/brand/confirm")
def confirm_brand_payment(payment_intent_id: str = Form(...),
                          current_user=Depends(get_current_user)):
    if current_user["role"] != "brand":
        raise HTTPException(403, "Brands only")
    try:
        intent = stripe.PaymentIntent.retrieve(payment_intent_id)
    except stripe.error.StripeError as e:
        raise HTTPException(400, str(e))
    if intent.status != "succeeded":
        raise HTTPException(400, f"Payment not succeeded. Status: {intent.status}")

    pay_record = payments_col.find_one_and_update(
        {"stripe_pi_id": payment_intent_id},
        {"$set": {"status": "completed", "paid_at": datetime.utcnow().isoformat()}}
    )
    if pay_record:
        amount_inr = int(pay_record.get("amount", 0)) // 100
        push_notification(pay_record["artist_id"],
            f"💰 {pay_record['brand_name']} sent you ₹{amount_inr:,} — '{pay_record['desc']}'")
    return {"message": "Payment confirmed"}


@app.get("/payments/brand/history")
def brand_payment_history(current_user=Depends(get_current_user)):
    if current_user["role"] != "brand":
        raise HTTPException(403, "Brands only")
    pays = []
    for p in payments_col.find({"brand_id": str(current_user["_id"]),
                                 "type": "brand_payment"}).sort("created_at", -1):
        p = to_str_id(p)
        raw = p.get("amount", 0)
        p["amount_inr"] = int(raw) // 100 if raw > 1000 else int(raw)
        pays.append(p)
    return pays


@app.get("/payments/artist/received")
def artist_received_payments(current_user=Depends(get_current_user)):
    return [to_str_id(p) for p in
            payments_col.find({"artist_id": str(current_user["_id"]),
                               "type": "brand_payment", "status": "completed"}).sort("paid_at", -1)]


# ═══════════════════════════════════════════════════════════════
# STRIPE WEBHOOK
# ═══════════════════════════════════════════════════════════════

@app.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    payload    = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    if webhook_secret:
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        except stripe.error.SignatureVerificationError:
            raise HTTPException(400, "Invalid signature")
    else:
        import json
        event = json.loads(payload)

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        meta    = session.get("metadata", {})
        ptype   = meta.get("type")
        if ptype == "tutorial":
            tutorial_id = meta.get("tutorial_id")
            payments_col.update_one({"stripe_session_id": session["id"]},
                                     {"$set": {"status": "completed",
                                               "paid_at": datetime.utcnow().isoformat()}})
            try:
                tut = tutorials_col.find_one({"_id": ObjectId(tutorial_id)})
                if tut:
                    tutorials_col.update_one({"_id": ObjectId(tutorial_id)},
                                             {"$inc": {"students": 1, "earnings": float(tut["price"])}})
                    push_notification(tut["artist_id"],
                        f"🎬 Someone purchased your tutorial '{tut['title']}' — ₹{tut['price']} earned!")
            except Exception:
                pass
        elif ptype == "artwork":
            orders_col.update_one({"stripe_session_id": session["id"]},
                                   {"$set": {"payment_status": "paid",
                                             "paid_at": datetime.utcnow().isoformat()}})
    return {"received": True}


# ═══════════════════════════════════════════════════════════════
# HEALTH
# ═══════════════════════════════════════════════════════════════

@app.get("/")
def root():
    return {"app": "ArtCraft API", "version": "1.0.0", "status": "running", "docs": "/docs"}


@app.get("/health")
def health():
    try:
        client.admin.command("ping")
        db_ok = True
    except Exception:
        db_ok = False
    return {"api": "ok", "mongodb": "ok" if db_ok else "error"}