ARG BASE_IMAGE=lean-agent-base:unconfigured
FROM ${BASE_IMAGE}
USER 0:0
COPY python/ /opt/python/
COPY tools/ /opt/acceptance/
COPY trusted/ /trusted/
ENV PATH=/opt/lean/bin:/usr/bin:/bin HOME=/tmp
WORKDIR /trusted
RUN /opt/python/bin/python3.12 --version \
 && /opt/acceptance/verify_exports --targets > /trusted/export-targets.txt \
 && LEAN_PATH=/trusted/.lake/build/lib/lean /opt/lean/bin/lean -j1 -o .lake/build/lib/lean/Challenge.olean Challenge.lean \
 && LEAN_PATH=/trusted/.lake/build/lib/lean /opt/acceptance/lean4export Challenge -- $(cat /trusted/export-targets.txt) > /trusted/challenge.ndjson \
 && chmod -R a+rX /opt/acceptance /trusted /opt/python
USER 1000:1000
ENTRYPOINT ["/opt/python/bin/python3.12", "/opt/acceptance/worker.py"]
