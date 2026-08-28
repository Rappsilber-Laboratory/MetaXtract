FROM python:3.11-slim-bullseye

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/opt/metaxtract
ENV PATH=/opt/venv/bin:$PATH

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        dirmngr \
        gnupg \
    && gpg --homedir /tmp --no-default-keyring \
        --keyring gnupg-ring:/usr/share/keyrings/mono-official-archive-keyring.gpg \
        --keyserver hkp://keyserver.ubuntu.com:80 \
        --recv-keys 3FA7E0328081BFF6A14DA29AA6A19B38D3D831EF \
    && chmod +r /usr/share/keyrings/mono-official-archive-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/mono-official-archive-keyring.gpg] https://download.mono-project.com/repo/debian stable-buster/snapshots/6.12.0.182 main" > /etc/apt/sources.list.d/mono-official-stable.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends mono-complete \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/metaxtract

COPY requirements-cli.txt ./
RUN python3 -m venv /opt/venv \
    && pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements-cli.txt

COPY . .

ENTRYPOINT ["python", "/opt/metaxtract/main.py"]
CMD ["--help"]
