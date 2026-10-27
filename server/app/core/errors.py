from fastapi import HTTPException


def unauthorized() -> HTTPException:
    return HTTPException(401, "Unauthorized", headers={"WWW-Authenticate": "Bearer"})


def forbidden() -> HTTPException:
    return HTTPException(403, "Forbidden")


def not_found() -> HTTPException:
    return HTTPException(404, "Not Found")
