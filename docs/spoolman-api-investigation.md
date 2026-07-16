# Spoolman API Investigation

No application code was modified for this investigation.

## Evidence Used

- Running container: `spoolman-spoolman-1`
- Image: `ghcr.io/donkie/spoolman:latest`
- Container label/version: `0.24.0`
- Container commit label: `103e029434ed6e6c6d218b52a422239eeb1d1b8e`
- Host mapping: `localhost:7912 -> container port 8000`
- Official Spoolman repository: <https://github.com/Donkie/Spoolman>
- Official REST API docs URL: <https://donkie.github.io/Spoolman/>

## Key Finding

The previously captured schema used the wrong OpenAPI endpoint.

`http://localhost:7912/openapi.json` is the root/application OpenAPI schema and only exposes app-level routes such as:

- `/metrics`
- `/config.js`

The correct REST API OpenAPI endpoint is:

```text
http://localhost:7912/api/v1/openapi.json
```

That schema reports:

```text
Title: Spoolman REST API v1
OpenAPI: 3.1.0
Server URL: /api/v1
Description: The API is served on the path /api/v1/
```

## Correct API Root

```text
http://localhost:7912/api/v1
```

Useful local docs endpoints:

```text
http://localhost:7912/api/v1/docs
http://localhost:7912/api/v1/redoc
http://localhost:7912/api/v1/openapi.json
```

## Vendor Endpoints

Relative to `/api/v1`:

```text
GET    /vendor
POST   /vendor
GET    /vendor/{vendor_id}
PATCH  /vendor/{vendor_id}
DELETE /vendor/{vendor_id}
GET    /export/vendors
```

## Filament Endpoints

Relative to `/api/v1`:

```text
GET    /filament
POST   /filament
GET    /filament/{filament_id}
PATCH  /filament/{filament_id}
DELETE /filament/{filament_id}
GET    /external/filament
GET    /export/filaments
```

## Spool Endpoints

Relative to `/api/v1`:

```text
GET    /spool
POST   /spool
GET    /spool/{spool_id}
PATCH  /spool/{spool_id}
DELETE /spool/{spool_id}
PUT    /spool/{spool_id}/use
PUT    /spool/{spool_id}/measure
GET    /export/spools
```

## Backup Endpoint

Relative to `/api/v1`:

```text
POST   /backup
```

The container source confirms this route in `spoolman/api/v1/router.py`; it triggers a database backup and is documented as only applicable for SQLite databases.

## Conclusion

The schema currently stored in `docs/spoolman-openapi.json` is valid JSON/OpenAPI, but it is the wrong schema for integration work. The project should use:

```text
http://localhost:7912/api/v1/openapi.json
```

as the source of truth for Spoolman `0.24.0` REST API integration.
