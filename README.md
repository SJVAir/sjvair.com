# SJVAir

San Joaquin Valley Air Quality Monitoring Platform

---

## 🛠 Tech Stack

- **Platform:** Python, Django
- **Database:** PostgreSQL with PostGIS
- **Cache:** Memcached
- **Task Queue:** Huey with Redis backend
- **Containerization:** Docker (via `docker compose`)
- **Testing:** pytest, Django test framework

---

## 🚀 Getting Started (with Docker)

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running.
- Git and Python 3.11+ installed on your host (only needed for optional local scripts).

---

### 🔧 Setup Instructions

1. **Clone the repository**

   ```bash
   git clone git@github.com:SJVAir/sjvair.com.git
   cd sjvair.com
   ```

2. **Build and start the dev environment**

   ```bash
   docker compose --profile dev up --build
   ```

   This will spin up the following services:

   - PostGIS (PostgreSQL + spatial extensions)
   - Redis
   - Memcached
   - Django web server
   - Huey task queues (`primary` and `secondary`)

3. **Create a superuser**

   Once the containers are up:

   ```bash
   docker compose exec web python manage.py createsuperuser
   ```

4. **Build frontend assets**

   ```bash
   docker compose exec web yarn install
   docker compose exec web invoke build
   ```

5. **Visit the app**

   [http://localhost:8000](http://localhost:8000)

---

## 🧪 Running Tests

```bash
docker compose --profile test run --rm test
```

Or with flags:

```bash
docker compose --profile test run --rm test pytest -s -x -k "test_something"
```

---

## 📦 Managing Dependencies

### Python dependencies

Install a new Python dependency:

```bash
# Add it to requirements/base.txt or requirements/develop.txt first
docker compose exec web pip install new-lib-name
```

### Frontend packages

Install frontend packages:

```bash
docker compose exec web yarn add new-js-lib
```

---

## 🛠️ Useful Commands

### Run migrations

```bash
docker compose exec web python manage.py migrate
```

### Open a shell in the web container

```bash
docker compose exec web bash
```

---

## 🧹 Cleaning Up

Stop and remove all containers:

```bash
docker compose down
```

Start up again later:

```bash
docker compose --profile dev up
```

---

## 🧰 Optional: Clear task queue and entries

```bash
docker compose exec web python manage.py clear_huey_and_entries
```

---

## 🧠 Notes

- `.env` and `.env.test` control environment-specific settings.
- Profiles let you selectively spin up only needed services:

  ```bash
  # Start dev environment
  docker compose --profile dev up

  # Run tests in isolation
  docker compose --profile test run --rm test
  ```

- The database persists between sessions in the `pgdata` volume.

---
