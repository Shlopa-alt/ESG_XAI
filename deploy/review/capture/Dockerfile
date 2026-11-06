FROM mcr.microsoft.com/playwright:v1.49.1-noble
WORKDIR /tool
RUN npm init -y >/dev/null && npm install --no-audit --no-fund playwright@1.49.1 @axe-core/playwright@4.10.1
COPY capture.mjs ./
ENTRYPOINT ["node", "/tool/capture.mjs"]
