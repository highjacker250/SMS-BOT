FROM python:3.11-slim

# WARP ke liye zaroori packages (sirf curl aur basic tools)
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies install karo
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Baaki code copy karo
COPY . .

# Bot start karo
CMD ["python", "main.py"]
