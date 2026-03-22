# Incoming — Brief Drop Zone

Drop briefs, memos, and filed documents here for citation extraction.

## Workflow
1. On Mac: use `onedrive_cli.py` to pull specific briefs you want indexed
2. Copy them here: `cp ~/Downloads/brief.pdf incoming/`
3. Commit and push: `git add incoming/ && git commit -m "briefs for extraction" && git push`
4. On enlightenment (or via Slack): run the processor

```bash
# Process everything in incoming/
python projects/case-research/process_incoming.py

# Or from Slack:
# "process the incoming briefs"
```

## What happens
- Each file gets its citations extracted
- Citations are resolved against CourtListener (full text pulled)
- Results saved to research library under auto-detected categories
- Processed files moved to `incoming/processed/`

## Supported formats
- `.md` — read directly
- `.txt` — read directly
- `.pdf` — requires `pdftotext` (poppler-utils)
- `.docx` — requires `python-docx`
