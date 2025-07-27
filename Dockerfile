# Use the official slim Python 3.11 image as base
FROM python:3.11-slim

# Enable colored terminal output
ENV FORCE_COLOR=1

# Prevent Python from writing .pyc files
ENV PYTHONDONTWRITEBYTECODE=1

# Force stdout/stderr to be unbuffered (real-time logs)
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install system dependencies
# - Build tools for compiling Python packages with C extensions
# - GDAL/Proj/PostGIS support for geospatial libraries
# - Node.js & Yarn for frontend assets
# - PostgreSQL & Redis clients for dev/debugging
RUN apt-get update && apt-get install -y \
    binutils \
    build-essential \
    curl \
    gdal-bin \
    git \
    libgdal-dev \
    libjpeg-dev \
    libpq-dev \
    libproj-dev \
    libssl-dev \
    libtiff5-dev \
    netcat-openbsd \
    postgresql-client \
    redis-tools \
    zlib1g-dev \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && npm install --global yarn \
    && rm -rf /var/lib/apt/lists/*

# Copy helper script and make it executable
COPY scripts/wait-for-services.sh /usr/local/bin/wait-for-services.sh
RUN chmod +x /usr/local/bin/wait-for-services.sh

# Silence Git's safe directory warning (for volume mounts as root)
RUN git config --global --add safe.directory /app

# Install Python dependencies
COPY requirements ./requirements/
RUN pip install --upgrade pip \
    && pip install setuptools==70.3.0 wheel packaging \
    && pip install --no-cache-dir -r requirements/base.txt \
    && pip install --no-cache-dir -r requirements/develop.txt

# Copy the full project into the container
COPY . .

# Start with a bash shell (overridden in most services)
CMD ["bash"]
