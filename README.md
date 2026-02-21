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
