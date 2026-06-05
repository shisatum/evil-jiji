# Jiji — Claude Code Instructions

## Version numbering

**Current version: v1.27**

Increment the minor version number (`v1.XX`) with every update, regardless of whether the change is on a feature branch or directly on main.

Version appears in two places in `main.py` — both must be updated together:
- Line 1: `# Jiji v1.24` (file header comment)
- Startup print in `create_jiji()`: `"Jiji V1.24 online. ..."`
