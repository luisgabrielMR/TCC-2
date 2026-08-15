FROM mcr.microsoft.com/dotnet/sdk:8.0@sha256:306301580fcaa5b445180e759db59309979002d1000669cb4cf58a567d0014bc AS build

WORKDIR /src

COPY DotnetApi.csproj packages.lock.json ./
RUN dotnet restore --locked-mode

COPY Program.cs .
RUN dotnet publish -c Release -o /out --no-restore

FROM mcr.microsoft.com/dotnet/aspnet:8.0@sha256:b0beb9cc1dee1c1b0749796110d4734292071b814207ad0d4f40611f7db04f7b

ENV ASPNETCORE_URLS=http://0.0.0.0:8000
ENV PORT=8000

WORKDIR /app
COPY --from=build /out .

EXPOSE 8000

CMD ["dotnet", "DotnetApi.dll"]
