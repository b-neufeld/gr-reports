# Use official Python image
FROM python:3.11-slim

# Set workdir inside the container
WORKDIR /app

# Copy requirements and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Expose port
EXPOSE 8000

# Run the app 
CMD ["python", "app.py"]