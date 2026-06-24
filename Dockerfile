FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Maigret in its own venv so its deps never collide with the app's.
# The app calls it over the CLI at MAIGRET_BIN. DejaVu gives Unicode PDFs.
RUN apt-get update && apt-get install -y --no-install-recommends git fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && python -m venv /opt/maigret \
    && /opt/maigret/bin/pip install --no-cache-dir maigret
ENV MAIGRET_BIN=/opt/maigret/bin/maigret

# Holehe (email OSINT) in its own venv too.
RUN python -m venv /opt/holehe \
    && /opt/holehe/bin/pip install --no-cache-dir holehe
ENV HOLEHE_BIN=/opt/holehe/bin/holehe

# App dependencies (installed system-wide, readable by the non-root user).
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Run as a non-root user (required/best-practice on Hugging Face Spaces).
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PORT=7860
WORKDIR /home/user/app
COPY --chown=user app ./app

EXPOSE 7860
# Shell form so $PORT is expanded (7860 on Hugging Face, override locally).
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
