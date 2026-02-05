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

## Questions?

Feel free to open an issue or reach out to the maintainers.

Thank you for contributing!
