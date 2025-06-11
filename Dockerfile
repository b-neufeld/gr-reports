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

# Copy your code and the emoji font
COPY . /app

RUN apt-get update && apt-get install -y \
    cron \
    curl \
    fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
    
# Set up cron job
RUN echo "0 6 * * * root /usr/local/bin/python /app/app.py >> /var/log/cron.log 2>&1" > /etc/cron.d/daily-collage
RUN chmod 0644 /etc/cron.d/daily-collage && crontab /etc/cron.d/daily-collage

# Set up log file
RUN touch /var/log/cron.log

# Expose port
EXPOSE 5000

# Run the app 
CMD python /app/app.py && cron && python /app/server.py

