"""ACS in-project calls through API Gateway: ESP sets Authorization to SA OIDC toward Cloud Run.
Every service passes the end-user Firebase ID in this header; db handlers must read it first."""

USER_JWT_HEADER = "X-Firebase-Authorization"
