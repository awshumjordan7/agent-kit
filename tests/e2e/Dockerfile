FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends python3 git jq nodejs && rm -rf /var/lib/apt/lists/*
WORKDIR /agent-kit
COPY . .
USER nobody
CMD ["sh", "tests/e2e/run.sh"]
