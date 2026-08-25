FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

EXPOSE 3000
# --host binds beyond localhost so the port mapping actually reaches the dev server.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
