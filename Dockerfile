# Use the official slim Python 3.11 image as base
FROM python:3.11-slim AS base

# Enable colored terminal output
ENV FORCE_COLOR=1

# Prevent Python from writing .pyc files
ENV PYTHONDONTWRITEBYTECODE=1

# Force stdout/stderr to be unbuffered (real-time logs)
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    binutils \
    build-essential \
    curl \
    gdal-bin \
    git \
    iputils-ping \
    libgdal-dev \
    libjpeg-dev \
    libpq-dev \
    libproj-dev \
    libssl-dev \
    libtiff5-dev \
    zlib1g-dev\
    && rm -rf /var/lib/apt/lists/*

# Silence Git's safe directory warning (for volume mounts as root)
RUN git config --global --add safe.directory /app

# Install Python dependencies
COPY requirements ./requirements/
RUN pip install --upgrade pip
RUN pip install setuptools==70.3.0 wheel packaging
RUN pip install --no-cache-dir -r requirements/base.txt

# Copy the full project into the container
COPY . .

# Start with a bash shell (overridden in most services)
CMD ["bash"]


# WEB CONTAINER
FROM base AS web

RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get update && apt-get install -y nodejs \
    && npm install --global yarn \
    && rm -rf /var/lib/apt/lists/*

# TEST CONTAINER
FROM base AS test

RUN pip install --no-cache-dir -r requirements/develop.txt
