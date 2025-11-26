# Dockerfile

FROM python:3.9-slim

# Set the working directory
WORKDIR /app

# Copy all files from current directory to the container
COPY . /app

# Install required Python packages
RUN pip install --no-cache-dir pandas matplotlib seaborn

# Run the data processing script
CMD ["python", "app/data_analysis.py"]
