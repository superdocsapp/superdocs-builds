# Production image for the review console. Builds the static bundle
# with the real backend URL baked in (VITE_API_BASE is a build-time
# arg -- Vite inlines it, it can't be swapped at container start the
# way a server-rendered app's env vars can), then serves it with a
# minimal static file server.
FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci || npm install
COPY . .
ARG VITE_API_BASE=http://localhost:8000
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

FROM node:20-slim
WORKDIR /app
RUN npm install -g serve
COPY --from=build /app/dist ./dist
EXPOSE 4173
CMD ["serve", "-s", "dist", "-l", "4173"]
