import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Agents Flow administrative console")
    commands = parser.add_subparsers(dest="command", required=True)

    admin = commands.add_parser("create-admin", help="Create an administrator")
    admin.add_argument("--email", help="Defaults to ADMIN_EMAIL")
    admin.epilog = "Password: ADMIN_PASSWORD environment variable or a hidden prompt."

    project = commands.add_parser("create-project", help="Create a project")
    project.add_argument("name")
    project.add_argument("--description")
    project.add_argument("--telegram-chat-id")

    category = commands.add_parser("create-category", help="Create a skill category")
    category.add_argument("name")
    category.add_argument("--description", default="")
    category.add_argument("--sort-order", type=int, default=0)

    commands.add_parser("seed-skills", help="Create MVP categories and four starter skills (idempotent)")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    # Keep --help usable before configuration, dependencies, or database setup.
    from pydantic import ValidationError
    from sqlalchemy.exc import SQLAlchemyError

    try:
        from app.core.db import SessionLocal
        from app.console.commands import execute

        with SessionLocal() as session:
            result = execute(session, args)
            session.commit()
    except ValidationError:
        parser.exit(2, "Invalid configuration or command input; check the environment and arguments.\n")
    except (ValueError, EOFError) as error:
        parser.exit(2, f"{error}\n")
    except SQLAlchemyError:
        parser.exit(1, "Database operation failed; check connectivity and run alembic upgrade head.\n")
    except KeyboardInterrupt:
        parser.exit(130, "Cancelled.\n")
    print(result)


if __name__ == "__main__":
    main()
