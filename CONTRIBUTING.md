# Contributing

Thanks for your interest! Issues and pull requests are welcome.

```bash
pip install -e ".[all,dev]"
ruff check .
python -m pytest
```

- Code, comments, option names and documentation are in English; texts shown in the
  images are translated through `--lang`.
- Keep `README.md` and `README.pt.md` in step when an option or behaviour changes.
- When you change drawing code, render a few images before and after (the graph, a map
  as `.png` and `.svg`, a short animation with `--step 97`) and check that only what you
  meant to change is different.
- `ruff check .` and the tests must pass; CI runs both on Linux and Windows.
