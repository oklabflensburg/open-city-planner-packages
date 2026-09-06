"""Apply credentialed CORS only to auth/account routes, keeping Registry CORS intact."""

from fastapi.middleware.cors import CORSMiddleware


class AuthCorsMiddleware:
    def __init__(self, app, origins):
        self.app = app
        self.auth_app = CORSMiddleware(
            app,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Content-Type", "X-CSRF-Token"],
        )

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] == "http" and path.startswith(("/api/v1/auth/", "/api/v1/users/")):
            await self.auth_app(scope, receive, send)
        else:
            await self.app(scope, receive, send)
