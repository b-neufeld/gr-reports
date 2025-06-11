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

# Copy source code
# COPY . .
# Copy your code and the emoji font
COPY . /app

# Copy requirements and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the emoji font explicitly (optional if not using system-installed one)
#COPY NotoColorEmoji.ttf /usr/share/fonts/truetype/noto/NotoColorEmoji.ttf

# Rebuild font cache (important!)
# RUN fc-cache -f -v

# Expose port
EXPOSE 8000

# Run the app 
CMD ["python", "app.py"]