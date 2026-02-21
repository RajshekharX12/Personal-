🚀 888 Rental Bot
A production-ready Telegram bot for managing +888 number rentals, transfers, renewals, and TON-based payments with concurrency safety and abuse protection.
✨ Features
🔢 Number rental & ownership system
🔄 Secure number transfers
⏳ Expiry-based rental lifecycle
💳 TON payment integration
🔐 Atomic Redis locking (race-condition safe)
🚦 Per-user rate limiting
🛡 One-time payment validation (replay protected)
📜 Ownership history tracking
👮 Admin action logging
⚡ Async architecture (Aiogram-based)
🏗 Architecture Overview
Copy code

handlers/        → Telegram command & callback handlers  
services/        → Business logic layer  
repositories/    → Redis interaction layer  
core/            → Middleware, locking, utilities
Tech Stack
Python 3.10+
Aiogram (async Telegram framework)
Redis (data store + locking)
TON API (payment validation)
Async HTTP clients
🔐 Concurrency & Safety
The system is built for public-scale usage.
Protection Mechanisms
Atomic Redis locking (SET NX EX)
Atomic rent/transfer operations
Per-user rate limiting (Redis INCR + EXPIRE)
Strict payment idempotency
Replay attack prevention
Expiry-safe renewal logic
💳 Payment Integrity
Each payment must:
Match exact amount
Match unique payload
Be within expiry window
Not be previously processed
Processed transactions are permanently marked to prevent reuse.
🧠 Data Model (Redis)
rental:{number} → Rental data (owner, expiry, etc.)
expiry:zset → Sorted set for expiry tracking
history:number:{number} → Ownership history
audit:admin → Admin action log
lock:number:{number} → Concurrency lock keys
rate:{user_id} → Rate limiting keys
🛠 Installation
1️⃣ Clone Repository
Bash
Copy code
git clone <your-repo-url>
cd <repo-folder>
2️⃣ Create Virtual Environment
Bash
Copy code
python3 -m venv venv
source venv/bin/activate
3️⃣ Install Dependencies
Bash
Copy code
pip install -r requirements.txt
4️⃣ Configure Environment Variables
Create a .env file:
Copy code

BOT_TOKEN=your_bot_token
API_ID=your_api_id
API_HASH=your_api_hash
REDIS_URI=your_redis_uri
TON_API_TOKEN=your_ton_api_token
OWNER_ID=your_telegram_id
▶️ Running the Bot
Bash
Copy code
python -m bot
Or if using systemd / screen / tmux:
Bash
Copy code
screen -S rentalbot
python -m bot
🗄 Backup Strategy (Recommended)
Enable Redis RDB snapshots
Daily automated backup
Encrypted off-server backup
Periodic restore testing
📈 Scaling Guidelines
For high traffic:
Use shared Redis instance
Run multiple bot replicas
Monitor Redis memory usage
Monitor lock collision metrics
Add external API request queue if necessary
🔍 Monitoring Suggestions
Recommended metrics to track:
Active rentals
Daily transfers
Failed payments
Rate limit hits
Lock contention count
Redis memory usage
⚠️ Production Notes
Never hardcode secrets
Rotate payment keys periodically
Monitor payment confirmations
Keep Redis secured (password + firewall)
📜 License
Private project. All rights reserved.
