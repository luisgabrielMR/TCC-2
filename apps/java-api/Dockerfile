FROM maven:3.9-eclipse-temurin-21@sha256:c07f7ccfb8ca6c9fa29ee523f00afa7d2ca6132c92f8652c4aebb5ee3491f502 AS build

WORKDIR /src

COPY pom.xml .
RUN mvn -q dependency:go-offline

COPY src ./src
RUN mvn -q package -DskipTests

FROM eclipse-temurin:21-jre@sha256:371da296b8cb74c7e53fbe7083d5374befc0011b493231d97d45fa789915e434

ENV PORT=8000

WORKDIR /app
COPY --from=build /src/target/java-api-0.1.0.jar /app/java-api.jar

EXPOSE 8000

CMD ["java", "-jar", "/app/java-api.jar"]
