# Môi trường chạy toàn bộ pipeline Nhóm 7: Python 3.11 + Java 17 (Spark) + elan (Lean 4) + LeanDojo.
# Pin bookworm: bản trixie không còn openjdk-17.
FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/work \
    PIP_NO_CACHE_DIR=1 \
    JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 \
    PATH=/root/.elan/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
        openjdk-17-jre-headless git wget curl ca-certificates make build-essential procps \
    && rm -rf /var/lib/apt/lists/*

# Lean 4 toolchain manager; LeanDojo tự cài đúng toolchain theo từng repo khi trace.
RUN curl -sSfL https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh \
        | sh -s -- -y --default-toolchain none

WORKDIR /work
COPY requirements.txt requirements-lean.txt ./
RUN pip install -r requirements.txt
ARG WITH_LEAN=1
RUN if [ "$WITH_LEAN" = "1" ]; then pip install -r requirements-lean.txt; fi

EXPOSE 8501 4040
CMD ["bash"]
