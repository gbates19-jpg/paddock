# UNTESTED — see ../README.md "Docker" section. Dev-mode only: runs the Vite
# dev server (project has no production build/serve stage yet), same as
# `npm run dev` on bare metal — just containerised so both halves of the
# stack start with one `docker compose up`.
FROM node:22-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev"]
