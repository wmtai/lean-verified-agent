FROM debian:bookworm-slim

ARG LEAN_VERSION=4.34.1
ARG TARGETARCH
RUN test "$TARGETARCH" = "amd64" \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl zstd \
    && curl --fail --location --retry 3 \
       "https://github.com/leanprover/lean4/releases/download/v${LEAN_VERSION}/lean-${LEAN_VERSION}-linux.tar.zst" \
       -o /tmp/lean.tar.zst \
    && mkdir /opt/lean \
    && tar --zstd -xf /tmp/lean.tar.zst --strip-components=1 -C /opt/lean \
    && rm /tmp/lean.tar.zst \
    && apt-get purge -y curl zstd \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/lean/bin:${PATH}"
ENV LEAN_PATH=/opt/verifier
COPY lean/Trusted/Audit.lean /opt/verifier/Trusted/Audit.lean
WORKDIR /opt/verifier
RUN lean -j1 -M2048 -o Trusted/Audit.olean Trusted/Audit.lean \
    && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin verifier \
    && chmod -R a+rX /opt/lean /opt/verifier
USER 10001:10001
WORKDIR /submission
CMD ["lean", "-j1", "-M2048", "Candidate.lean"]
