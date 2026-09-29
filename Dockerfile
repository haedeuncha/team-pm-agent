# GitHub Actions 밖(사내 서버, Kubernetes CronJob 등)에서 실행할 때 사용
#   docker build -t team-pm-agent .
#   docker run --rm --env-file .env -v $PWD/state:/app/.pm-agent-state team-pm-agent pm_agent.run --scheduled
#   docker run --rm --env-file .env -v $PWD/state:/app/.pm-agent-state team-pm-agent pm_agent.publish report.md
# 승인 단계(GitHub Environment)는 Actions 에만 있으므로, 서버 실행 시 publish 를 누가 언제 실행할지 운영 규칙을 정하세요.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt requirements-llm.txt ./
RUN pip install -r requirements.txt -r requirements-llm.txt

COPY pm_agent ./pm_agent
COPY config.yaml ./

RUN useradd --create-home --uid 10001 pmagent && mkdir -p /app/.pm-agent-state && chown -R pmagent /app
USER pmagent

ENTRYPOINT ["python", "-m"]
CMD ["pm_agent.run", "--scheduled"]
