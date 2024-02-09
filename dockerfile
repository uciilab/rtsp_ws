FROM ubuntu:latest
# Set noninteractive mode to avoid timezone configuration prompt
ENV DEBIAN_FRONTEND=noninteractive
ENV RTSP_URL="rtsp://labstudent:Erclab_717@192.168.0.88:554/vcd=2"
# Update package list and install essential dependencies
RUN apt-get update && apt-get install -y \
    sudo \
    vim \
    wget \
    build-essential \
    pkg-config \
    python3 \
    python3-pip \
    python3-dev \
    libgirepository1.0-dev \
    libcairo2-dev \
    gstreamer1.0 \
    gstreamer1.0-dev \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly \
    gstreamer1.0-libav \
    gstreamer1.0-tools \
    gstreamer1.0-x \
    gstreamer1.0-alsa \
    gstreamer1.0-gl \
    gstreamer1.0-gtk3 \
    gstreamer1.0-qt5 \
    gstreamer1.0-pulseaudio \
    python3-gst-1.0 \
    gir1.2-gstreamer-1.0 \
    python3-gi 

# Install the gi-dev package manually
RUN apt-get install -y libgirepository1.0-dev


WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy the rest of your application code
COPY . .

EXPOSE 80

CMD ["python3","main.py"]
