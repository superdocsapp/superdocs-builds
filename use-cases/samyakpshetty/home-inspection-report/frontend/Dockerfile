# The inspector's interface. Vite dev server, bound to all interfaces so it is reachable
# from the host when it runs inside compose.
FROM node:22-alpine

WORKDIR /app

# Manifest first so the install layer caches across source edits.
COPY package.json package-lock.json* ./
RUN npm install

COPY . .

EXPOSE 5174
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5174"]
