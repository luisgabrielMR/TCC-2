FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build

WORKDIR /src

COPY DotnetApi.csproj .
RUN dotnet restore

COPY Program.cs .
RUN dotnet publish -c Release -o /out --no-restore

FROM mcr.microsoft.com/dotnet/aspnet:8.0

ENV ASPNETCORE_URLS=http://0.0.0.0:8000
ENV PORT=8000

WORKDIR /app
COPY --from=build /out .

EXPOSE 8000

CMD ["dotnet", "DotnetApi.dll"]
