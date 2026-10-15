# The setup script creates a filtered temporary context, never the repository.
FROM ubuntu:24.04
COPY toolchain/ /opt/lean/
COPY trusted/ /trusted/
ENV PATH=/opt/lean/bin:/usr/bin:/bin \
    HOME=/tmp \
    LEAN_PATH=/trusted/.lake/build/lib/lean
WORKDIR /trusted
RUN lean --version && lake build && chmod -R a+rX /trusted /opt/lean
USER 1000:1000
ENTRYPOINT ["/opt/lean/bin/lean"]
