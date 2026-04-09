FROM python:3.11-slim

# Install cloudflared
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" \
      > /etc/apt/sources.list.d/cloudflared.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends cloudflared && \
    apt-get purge -y curl && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
