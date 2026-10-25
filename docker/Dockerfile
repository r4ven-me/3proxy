FROM debian:trixie-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl gcc libc6-dev make \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
# Immutable upstream commit for 3proxy 0.9.5.
RUN curl -fsSL --retry 3 https://codeload.github.com/3proxy/3proxy/tar.gz/f23fc4fc4458606a257a9f26bc37251fc60e1cc7 \
    | tar xz --strip-components=1 \
    && make -f Makefile.Linux -j2 PLUGINS= \
    && strip bin/3proxy

FROM debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-yaml \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /src/bin/3proxy /usr/local/bin/3proxy
COPY --chmod=755 src/proxy.py /usr/local/bin/interface-proxy
COPY --chmod=755 scripts/foxyproxy.sh /usr/local/bin/foxyproxy.sh
USER 65534:65534
ENTRYPOINT ["/usr/local/bin/interface-proxy"]
CMD ["serve"]
