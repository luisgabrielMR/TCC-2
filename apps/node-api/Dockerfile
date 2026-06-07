FROM node:22-slim

ENV NODE_ENV=production
ENV PORT=8000

WORKDIR /app

COPY package.json .
RUN npm install --omit=dev

COPY src ./src

EXPOSE 8000

CMD ["node", "src/server.js"]
