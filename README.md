```markdown
# 📱 888 Rental Bot

A production-ready Telegram bot for managing +888 number rentals, secure transfers, renewals, and TON-based payments. Built with concurrency safety, abuse protection, and atomic operations in mind.

## ✨ Features

- 🔢 **Number rental & ownership system** – Rent and own virtual numbers with expiration tracking.
- 🔄 **Secure number transfers** – Transfer ownership safely with atomic locking.
- ⏳ **Expiry-based rental lifecycle** – Automatic expiry and renewal handling.
- 💳 **TON payment integration** – Accept payments via The Open Network (TON).
- 🔐 **Atomic Redis locking** – Race‑condition safe operations.
- 🚦 **Per‑user rate limiting** – Prevent abuse and spam.
- 🛡 **One‑time payment validation** – Replay‑proof transactions.
- 📜 **Ownership history tracking** – Keep a log of all transfers.
- 👮 **Admin action logging** – Full audit trail for administrative actions.
- ⚡ **Async architecture** – Built on Aiogram for high concurrency.

## 🏗 Architecture Overview

```

handlers/         → Telegram command & callback handlers
services/         → Business logic layer
repositories/     → Redis interaction layer
core/             → Middleware, locking, utilities

```

## 🧰 Tech Stack

- **Python 3.10+**
- **Aiogram** – Asynchronous Telegram framework
- **Redis** – Data store + distributed locking
- **TON API** – Payment validation
- **Async HTTP clients** – For external API calls

## 🔒 Concurrency & Safety

The system is engineered for public‑scale usage with multiple protection layers:

- **Atomic Redis locking** (`SET NX EX`) – Prevents race conditions on critical operations.
- **Atomic rent/transfer operations** – Each state change is isolated.
- **Per‑user rate limiting** – Uses `INCR` + `EXPIRE` to limit request frequency.
- **Strict payment idempotency** – Each payment is processed exactly once.
- **Replay attack prevention** – Expiring payloads and one‑time validation.
- **Expiry‑safe renewal logic** – Renewals are atomic and cannot overlap.

## 💳 Payment Integrity

Every payment must satisfy all of the following before being accepted:

- Amount matches the exact rental price.
- Payload is unique and tied to the specific transaction.
- Transaction is within the allowed time window.
- Payment has never been processed before (idempotency key in Redis).

Once processed, the transaction is permanently marked to prevent reuse.

## 🧠 Data Model (Redis)

| Key pattern                 | Description                               |
|-----------------------------|-------------------------------------------|
| `rental:{number}`           | Rental data (owner, expiry, etc.)         |
| `expiry:zset`               | Sorted set for expiry tracking            |
| `history:number:{number}`   | Ownership history                         |
| `audit:admin`               | Admin action log                          |
| `lock:number:{number}`      | Concurrency lock for a specific number    |
| `rate:{user_id}`            | Rate limiting counters                    |

## 🛠 Installation

### 1️⃣ Clone the repository

```bash
git clone https://github.com/yourusername/888-rental-bot.git
cd 888-rental-bot
```

2️⃣ Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate
```

3️⃣ Install dependencies

```bash
pip install -r requirements.txt
```

4️⃣ Configure environment variables

Create a .env file in the project root:

```
BOT_TOKEN=your_bot_token
API_ID=your_api_id
API_HASH=your_api_hash
REDIS_URI=your_redis_uri
TON_API_TOKEN=your_ton_api_token
OWNER_ID=your_telegram_id
```

▶️ Running the Bot

```bash
python -m bot
```

For production, consider using systemd, supervisor, or a process manager like pm2.

🗄 Backup Strategy

· Enable Redis RDB snapshots for persistence.
· Schedule daily automated backups (e.g., redis-cli SAVE and copy the dump).
· Store backups encrypted in an off‑server location.
· Periodically test restoration procedures.

📈 Scaling Guidelines

To handle high traffic:

· Use a dedicated Redis instance (or cluster).
· Run multiple bot replicas behind a load balancer.
· Monitor Redis memory usage and lock contention.
· Offload payment validation to a queue if API rate limits are hit.
· Set up Prometheus/Grafana dashboards for key metrics.

🔍 Monitoring Recommendations

Track the following metrics:

· Active rentals over time
· Daily transfers and new rentals
· Failed payments and rate limit hits
· Lock contention count
· Redis memory usage and command latency
· Bot response times

⚠️ Production Notes

· Never hardcode secrets – Always use environment variables.
· Rotate TON API keys periodically.
· Implement payment confirmation retries with exponential backoff.
· Secure Redis with a strong password and firewall rules.
· Keep the bot updated with the latest dependencies.

📄 License

Private project. All rights reserved.

```
