FROM node:22-alpine AS build
WORKDIR /ui
COPY package.json .
RUN npm install --no-audit --no-fund
COPY . .
RUN npm run build
FROM nginx:1.27-alpine
COPY --from=build /ui/dist /usr/share/nginx/html
