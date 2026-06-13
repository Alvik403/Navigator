FROM node:22-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
ARG VITE_KEYCLOAK_URL=http://localhost:8080
ARG VITE_WEB_ORIGIN=http://localhost:5173
ENV VITE_KEYCLOAK_URL=$VITE_KEYCLOAK_URL
ENV VITE_WEB_ORIGIN=$VITE_WEB_ORIGIN
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
