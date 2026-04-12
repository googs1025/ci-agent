"""Shared test fixtures."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ci_optimizer.db.models import Base


@pytest.fixture
def tmp_repo(tmp_path):
    """Create a temporary repo directory with a sample workflow."""
    workflows_dir = tmp_path / ".github" / "workflows"
    workflows_dir.mkdir(parents=True)

    ci_yml = workflows_dir / "ci.yml"
    ci_yml.write_text("""\
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 18
      - run: npm install
      - run: npm test

  lint:
    runs-on: ubuntu-latest
    needs: [test]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 18
      - run: npm install
      - run: npm run lint
""")

    deploy_yml = workflows_dir / "deploy.yml"
    deploy_yml.write_text("""\
name: Deploy
on:
  push:
    branches: [main]

permissions: write-all

jobs:
  deploy:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@main
      - run: echo ${{ github.event.pull_request.title }}
      - run: npm install
      - run: npm run build
      - run: npm run deploy
""")

    return tmp_path


@pytest.fixture
def tmp_repo_no_workflows(tmp_path):
    """Create a temporary repo with no workflow files."""
    return tmp_path


@pytest_asyncio.fixture
async def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()
