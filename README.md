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
   docker compose --profile web up
   ```

   This will spin up the following services:

   - PostGIS (PostgreSQL + spatial extensions)
   - Redis
   - Memcached
   - Django web server
   - Primary task queue

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
docker compose run --rm test
```

Or with flags:

```bash
docker compose run --rm test pytest -s -x -k "test_something"
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

### Import all regional data

```bash
docker compose exec web bash -c "
  python manage.py migrate regions zero &&
  python manage.py migrate regions &&
  python manage.py import_counties &&
  python manage.py import_census_tracts &&
  python manage.py import_cities &&
  python manage.py import_school_districts &&
  python manage.py import_zipcodes &&
  python manage.py import_congressional_districts &&
  python manage.py import_state_assembly &&
  python manage.py import_state_senate &&
  python manage.py import_urban_areas &&
  python manage.py import_land_use &&
  python manage.py import_protected_areas
"
```

---

## 🧹 Cleaning Up

Stop and remove all containers:

```bash
docker compose down
```

Start up again later:

```bash
docker compose --profile web up
```

---

## 🧠 Notes

- `.env` and `.env.test` control environment-specific settings.
- Profiles let you selectively spin up only needed services:

  ```bash
  # Start dev environment
  docker compose --profile web up

  # Run tests in isolation
  docker compose --profile test run --rm test
  ```

- The database persists between sessions in the `pgdata` volume.

---
