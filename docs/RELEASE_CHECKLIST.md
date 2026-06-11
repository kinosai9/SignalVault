# Release Checklist

## Before Making Repository Public

- [x] `.env` not tracked in git, never committed to history
- [x] `.gitignore` excludes: `.env`, `.env.local`, `*.key`, `*.pem`, `*.token`, `backup/`, `data/podcast_analyst.db`, `data/user_settings.json`, `data/transcripts/`, `data/validation/`, `data/reports/*`, `logs/*`
- [x] `.env.example` uses only placeholder values
- [x] No API keys, tokens, or private keys in tracked source files
- [x] No personal filesystem paths in tracked files
- [x] Git author email sanitized (no personal email in commit history)
- [x] `README.md` reflects current implementation state
- [x] `LICENSE` file exists (MIT)
- [x] CI/CD pipeline configured (GitHub Actions)
- [x] All tests pass (`python -m pytest tests/ -v`)

## Before Local Delivery

- [ ] `.env` configured with valid `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`
- [ ] `data/user_settings.json` has correct `obsidian_vault_path`
- [ ] `pip install -e ".[dev]"` succeeds
- [ ] `python -m podcast_research serve` starts without errors
- [ ] Web Console accessible at `http://127.0.0.1:8000/`
- [ ] Dashboard shows Vault health status
- [ ] Source pages (channels, videos) load correctly with CSS
- [ ] Real LLM analysis works: `python -m podcast_research --youtube-url "URL" --no-mock`

## Before Each Release

- [ ] `python -m pytest tests/ -v` — all pass
- [ ] `ruff check src/ tests/` — clean
- [ ] `git status` — working tree clean
- [ ] `CHANGELOG.md` updated with this release's changes
- [ ] `docs/ROADMAP.md` reflects current completion status
- [ ] No `data/podcast_analyst.db`, `data/user_settings.json`, `data/subtitle.srt` or other local-only files staged
- [ ] CSS cache bust version updated in `base.html`
- [ ] Web Console smoke test passes (pages load without errors)
