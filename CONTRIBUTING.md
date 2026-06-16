# Contributing to PyMidscene

Thank you for your interest in contributing to PyMidscene! This document provides guidelines and instructions for contributing.

## Code of Conduct

Please be respectful and constructive in all interactions. We welcome contributors of all experience levels.

## How to Contribute

### Reporting Bugs

1. Check if the bug has already been reported in [Issues](https://github.com/AIPythoner/pymidscene/issues)
2. If not, create a new issue with:
   - A clear, descriptive title
   - Steps to reproduce the bug
   - Expected vs actual behavior
   - Your environment (Python version, OS, model used)

### Suggesting Features

1. Check existing issues for similar suggestions
2. Create a new issue with the "enhancement" label
3. Describe the feature and its use case

### Pull Requests

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes
4. Run tests: `pytest`
5. Format code: `black pymidscene tests`
6. Commit with clear messages
7. Push and create a Pull Request

## Development Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/pymidscene.git
cd pymidscene

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -e ".[dev]"

# Install Playwright browsers
playwright install chromium
```

## Code Style

- Follow PEP 8 guidelines
- Use type hints for all functions
- Write docstrings for public APIs
- Keep functions focused and small

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=pymidscene

# Run specific test
pytest tests/test_agent.py
```

## Commit Messages

Use clear, descriptive commit messages:

- `feat: add support for new model`
- `fix: correct XPath extraction for nested elements`
- `docs: update README with examples`
- `test: add tests for cache system`

## Publishing a Release (maintainers)

```bash
# 1. Update CHANGELOG (move [Unreleased] -> [X.Y.Z] - DATE) and bump the version
#    in BOTH pyproject.toml and pymidscene/__init__.py (keep them in sync).

# 2. Run the full test suite (from this directory)
venv/Scripts/python.exe -m pytest tests/

# 3. Build the wheel + sdist (output goes to dist/)
python -m build

# 4. Validate the artifacts and smoke-test the wheel in a clean environment
python -m twine check dist/*
python -m venv /tmp/pmcheck && /tmp/pmcheck/Scripts/python -m pip install dist/*.whl
#    then from outside the repo: `import pymidscene`, `pymidscene --help`, and
#    run tests/packaging/report_smoke.py (verifies bundled report resources load).

# 5. Publish to PyPI (needs a PyPI API token)
python -m twine upload dist/*

# 6. Tag the release
git tag vX.Y.Z && git push --tags
```

`dist/` is git-ignored — do not commit build artifacts.

## Questions?

Feel free to open an issue or reach out to the maintainers.

Thank you for contributing!
