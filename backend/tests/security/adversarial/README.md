# Adversarial corpus

Inputs the guardrail middleware must catch, and look-alike inputs it must let through.
`tests/security/test_adversarial.py` runs every case; CI reports it as its own step (`pytest -m adversarial`).

Each file has `attacks` (must be caught) and `benign` (must pass). A case is a string, or a
mapping with `text` and an optional `note`. Escapes such as `​` work in double-quoted
YAML strings, which is how the obfuscated cases spell zero-width and look-alike characters.

When a bypass is found: add it here first, watch the test fail, then fix the guard.

## Judge cases (`judge.yaml`)

Attacks the regex guards can't see — leetspeak, spaced-out letters, other languages,
paraphrase — go to the `custom_rule` judge instead. Each case is a prompt plus the answer a model
gave; the test first checks the regex guards really miss the prompt (if one starts catching it,
move the case to that guard's file), then checks the judge's verdict.

The judge's replies are in `judge_recorded.json`, keyed by `note`. They are hand-written for now.
To record them from a real model (the key comes from the vault or the provider's env var):

    PIPESETS_RECORD_JUDGE=anthropic/claude-haiku-5-5 pytest -m adversarial -k judge

That rewrites `judge_recorded.json` with what the model said; a failing case means that judge
misses that attack. Review the diff before committing it.
