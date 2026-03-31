# ArtCraft Backend — FastAPI + MongoDB + Stripe

## Tech Stack
- **FastAPI** — Python web framework
- **MongoDB + PyMongo** — Database (no Motor, no Beanie)
- **Stripe** — Payments (Checkout Sessions + PaymentIntents)
- **hashlib sha256** — Password hashing (no bcrypt)
- **Local file storage** — Uploads saved in `uploads/` folder

---

## Quick Setup

### 1. Install Python dependencies
```bash
pip install -r requirements.txt
```

### 2. Install & start MongoDB
```bash
# Ubuntu/Debian
sudo apt install mongodb
sudo systemctl start mongodb

# macOS (Homebrew)
brew tap mongodb/brew
brew install mongodb-community
brew services start mongodb-community

# Or use MongoDB Atlas (free cloud): https://www.mongodb.com/atlas
```

### 3. Configure environment
```bash
cp .env.example .env
# Edit .env with your Stripe keys and MongoDB URL
```

Get Stripe test keys from: https://dashboard.stripe.com/test/apikeys
- Publishable key starts with `pk_test_`
- Secret key starts with `sk_test_`

### 4. Run the server
```bash
uvicorn main:app --reload --port 8000
```

Visit http://localhost:8000/docs for interactive API docs.

---

## Frontend Integration

### Step 1: Add api.js to all HTML pages
```html
<!-- Add before </body> in login.html, artist.html, brand.html, customer.html -->
<script src="api.js"></script>
```

### Step 2: Replace login form
```javascript
// Old localStorage code:
// saveSession({ userId, role, name, email })

// New API code:
async function doLogin() {
  try {
    const data = await API.login(email, password, selectedRole);
    redirectTo(data.role);
  } catch (e) {
    showErr('login', e.message);
  }
}

async function doSignup() {
  try {
    const data = await API.signup(fname, lname, email, password, signupRole);
    redirectTo(data.role);
  } catch (e) {
    showErr('signup', e.message);
  }
}
```

### Step 3: Replace artwork upload
```javascript
// Old: state.artworks.push(...)
// New:
async function saveArtwork(status) {
  const imageFile = document.getElementById('art-file').files[0];
  const artwork = await API.uploadArtwork({
    title:  document.getElementById('art-title').value,
    price:  document.getElementById('art-price').value,
    medium: document.getElementById('art-medium').value,
    dims:   document.getElementById('art-dims').value,
    desc:   document.getElementById('art-desc').value,
    status,
    image: imageFile  // actual File object
  });
  showToast('Artwork saved!');
  renderPortfolio();
}
```

### Step 4: Replace tutorial upload
```javascript
async function saveTutorial() {
  const videoFile = document.getElementById('tut-video-file').files[0];
  const tutorial = await API.uploadTutorial({
    title:    document.getElementById('tut-title').value,
    price:    document.getElementById('tut-price').value,
    duration: document.getElementById('tut-duration').value,
    level:    document.getElementById('tut-level').value,
    lang:     document.getElementById('tut-lang').value,
    desc:     document.getElementById('tut-desc').value,
    video:    videoFile
  });
  showToast('Tutorial saved!');
  renderTutorials();
}
```

### Step 5: Replace buy artwork
```javascript
async function proceedPayment() {
  if (_payMethod === 'online') {
    const result = await API.buyArtwork(
      _buyArtId,
      document.getElementById('buy-address').value,
      document.getElementById('buy-phone').value,
      document.getElementById('buy-note').value,
      'online'
    );
    // Redirect to Stripe checkout
    window.location.href = result.checkout_url;
  } else {
    const result = await API.buyArtwork(
      _buyArtId, address, phone, note, 'cod'
    );
    showToast('COD order placed!');
  }
}
```

### Step 6: Replace buy tutorial
```javascript
async function openTutBuyModal(id) {
  const result = await API.buyTutorial(id);
  // Redirect to Stripe checkout
  window.location.href = result.checkout_url;
}
```

### Step 7: Handle payment return
Create `payment-success.html`:
```html
<script src="api.js"></script>
<script>
async function handleReturn() {
  const params = new URLSearchParams(location.search);
  const type = params.get('type');
  const sessionId = params.get('session_id');
  
  if (type === 'tutorial') {
    await API.verifyTutorialPayment(sessionId);
    window.location.href = 'customer.html';
  } else if (type === 'artwork') {
    await API.verifyArtworkPayment(sessionId);
    window.location.href = 'customer.html';
  }
}
handleReturn();
</script>
```

---

## API Reference

### Auth
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/signup` | Register user |
| POST | `/auth/login` | Login, returns token |
| POST | `/auth/logout` | Invalidate token |
| GET  | `/auth/me` | Get current user |

### Artworks
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/artworks` | Upload artwork (artist) |
| GET  | `/artworks` | List all listed artworks |
| GET  | `/artworks/mine` | Artist's own artworks |
| PUT  | `/artworks/{id}` | Update artwork |
| DELETE | `/artworks/{id}` | Delete artwork |

### Tutorials
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/tutorials` | Create tutorial (artist) |
| GET  | `/tutorials` | List tutorials (no video) |
| GET  | `/tutorials/{id}` | Get tutorial (video if paid) |
| GET  | `/tutorials/mine/purchased` | Customer's purchased tutorials |
| DELETE | `/tutorials/{id}` | Delete tutorial |

### Payments
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/payments/tutorial/checkout` | Create Stripe session |
| POST | `/payments/tutorial/verify` | Verify after payment |
| POST | `/payments/artwork/checkout` | Buy artwork |
| POST | `/payments/artwork/verify` | Verify artwork payment |
| POST | `/payments/brand/pay-artist` | Brand pays artist |

### Jobs & Competitions
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/jobs` | Create job (brand) |
| GET  | `/jobs` | List active jobs |
| POST | `/jobs/{id}/apply` | Artist applies |
| POST | `/competitions` | Create competition |
| POST | `/competitions/{id}/register` | Artist registers |

### Messages
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/messages/send` | Send message |
| GET  | `/messages/threads` | List conversations |
| GET  | `/messages/thread/{id}` | Get messages in thread |

---

## Stripe Webhook Setup

For production, set up a webhook in Stripe Dashboard:
- URL: `https://your-domain.com/webhook/stripe`
- Events: `checkout.session.completed`

Copy the webhook secret to `.env` as `STRIPE_WEBHOOK_SECRET`.

---

## MongoDB Collections

| Collection | Purpose |
|------------|---------|
| `users` | All users (artists, brands, customers) |
| `artworks` | Artwork listings |
| `tutorials` | Video tutorials |
| `orders` | Artwork purchase orders |
| `payments` | Payment records |
| `jobs` | Brand job postings |
| `applications` | Job applications |
| `competitions` | Brand competitions |
| `comp_registrations` | Artist comp entries |
| `messages` | Chat messages |
| `notifications` | User notifications |