# Use official Python image
FROM python:3.11-slim

# Install system dependencies for fonts and Pillow
RUN apt-get update && apt-get install -y \
    libfreetype6-dev \
    libraqm-dev \
    libjpeg-dev \
    libpng-dev \
    libopenjp2-7 \
    fontconfig \ 
    && apt-get clean

# Set workdir inside the container
WORKDIR /app
ENV PYTHONUNBUFFERED=1

# Copy code
COPY . /app

RUN apt-get update && apt-get install -y \
    curl \
    fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Expose port
EXPOSE 5000

# Run the app 
CMD python /app/server.py
