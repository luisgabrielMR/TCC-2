FROM maven:3.9-eclipse-temurin-21 AS build

WORKDIR /src

COPY pom.xml .
RUN mvn -q dependency:go-offline

COPY src ./src
RUN mvn -q package -DskipTests

FROM eclipse-temurin:21-jre

ENV PORT=8000

WORKDIR /app
COPY --from=build /src/target/java-api-0.1.0.jar /app/java-api.jar

EXPOSE 8000

CMD ["java", "-jar", "/app/java-api.jar"]
