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

# removed cron from this list 
RUN apt-get update && apt-get install -y \
    curl \
    fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
  
# REMOVE if threading works 
# Set up cron job
# RUN echo "0 6 * * * root /usr/local/bin/python /app/app.py >> /var/log/cron.log 2>&1" > /etc/cron.d/daily-collage
# RUN chmod 0644 /etc/cron.d/daily-collage && crontab /etc/cron.d/daily-collage
# Set up log file
# RUN touch /var/log/cron.log

# Expose port
EXPOSE 5000

# Run the app 
# CMD python /app/app.py && cron && python /app/server.py
CMD python /app/server.py
