# nk-data-story

![nk-data-story](https://raw.githubusercontent.com/NickkkLian/nickkk-skills/main/gallery/social/nk-data-story.png)

An agent skill for [Claude Code](https://code.claude.com) and [OpenAI Codex](https://developers.openai.com/codex). Turn a CSV or Excel file into a one-page data report whose headline is the conclusion and where every figure states its denominator, window and filter.

Part of [nickkk-skills](https://github.com/NickkkLian/nickkk-skills) — agent skills that ship a self-test with every script; the Verify
section below says which of them were broken on purpose before release to prove they react.

![nk-data-story demo: one idea in, a finished page out](https://raw.githubusercontent.com/NickkkLian/nickkk-skills/main/gallery/nk-data-story.gif)

## What it does

- The agent profiles the table (`profile.py`: kinds of columns, missing values, duplicates, ambiguous dates) and writes `report.json`: the decision the report serves, figures defined as computations, up to three charts, a next step and what the data cannot answer. It never types a number.
- `report_check.py` refuses typed numbers, shares without a denominator, changes without two periods, a missing decision and data that does not match its pinned sha256 (checks D01–D10).
- `render.py` recomputes every number from the file into one HTML page: each figure followed by its n, window and filter, bar and line charts, three palettes in light and dark.
- Standard library only; CSV and XLSX read locally. Each check has a sample only it catches, and each was broken on purpose to prove the self-test goes red.

The full procedure, the boundaries and where the rules came from are in [SKILL.md](SKILL.md).

## How it works

1. Profile before reading
2. Name the decision
3. Choose two to four figures that could change it
4. Write the prose with numbers only as references
5. At most three charts
6. Check
7. Render and look at it
8. Share the page, not retyped numbers

## Why it is built this way

**The idea.** A spreadsheet becomes one page a person can act on: the headline says what the data shows, every number on the page is recomputed from the file and followed by what it was computed on, and the page ends with what the data cannot answer. The agent never types a number into the report.

**Where it came from.** The author's own rules for analyses (2026), each written after a report went wrong in a way the reader could not see: percentages with no sample size, "growth" with no period, "the data shows" with no file behind it, and a number measured at the wrong level of aggregation, which happened four times before "say where, what statistic and at what level" became a rule.

**Evidence.** What was broken on purpose to show that the self-tests can fail is under [Verify](#verify); what was run end to end, and in which agent, is under [Compatibility](#compatibility).

## Install

Pick one of four ways: three for Claude Code, one for OpenAI Codex. Skills load when a session starts, so open a **new** session after installing.

### 1 · Terminal, one command

```bash
git clone https://github.com/NickkkLian/nk-data-story ~/.claude/skills/nk-data-story
```

1. Run the command above (for one project only, clone into `.claude/skills/nk-data-story` inside that project).
2. Start a new Claude Code session.
3. Check it loaded: type `/nk-data-story` — it appears in the slash-command menu. Or just ask for the task; the skill triggers on its own.

### 2 · Claude Code in a terminal session (plugin)

The plugin route goes through the [nickkk-skills](https://github.com/NickkkLian/nickkk-skills) marketplace. Add it once; after that each skill is one command.

```
/plugin marketplace add NickkkLian/nickkk-skills
/plugin install nk-data-story@nickkk-skills
```

1. In a Claude Code session, run the first line (once per machine).
2. Run the second line.
3. Start a new session (or run `/reload-plugins`). The skill shows up as `nk-data-story:nk-data-story`.

Without opening a session, the same two steps work from a shell: `claude plugin marketplace add NickkkLian/nickkk-skills` then `claude plugin install nk-data-story@nickkk-skills`.

### 3 · Claude desktop app (Code tab)

**Add the marketplace first — Discover only searches marketplaces you have already added.**

<img src="https://raw.githubusercontent.com/NickkkLian/nickkk-skills/main/gallery/panel-route/panel-route.gif" alt="Adding the marketplace and installing a skill in the desktop app" width="640">

<sub>Recorded on 2026-09-16, when the marketplace listed ten skills, all at version 0.1.0; it lists more now. The repository list in this recording shows the recorder's own repositories because a GitHub account is connected; yours will show yours. Type the full name as in step 4.</sub>

1. In the chat box, type `/plugin marketplace` and press Enter (or open **Settings → Customize → Plugins**). The **Plugins** panel opens.
   <br><img src="https://raw.githubusercontent.com/NickkkLian/nickkk-skills/main/gallery/panel-route/step1-type-plugin-marketplace.png" alt="/plugin marketplace typed in the chat box" width="480">
2. Top right, open **Add ▾** and choose **Add marketplace**.
   <br><img src="https://raw.githubusercontent.com/NickkkLian/nickkk-skills/main/gallery/panel-route/step2-add-menu.png" alt="The Add menu with Add marketplace" width="480">
3. Choose **Add from a repository**.
   <br><img src="https://raw.githubusercontent.com/NickkkLian/nickkk-skills/main/gallery/panel-route/step3-add-from-repository.png" alt="Add marketplace dialog: Add from a repository" width="480">
4. In **URL**, type the full `NickkkLian/nickkk-skills`. At the bottom of the list choose the row **Use "NickkkLian/nickkk-skills"**, then press **Sync**.
   <br><img src="https://raw.githubusercontent.com/NickkkLian/nickkk-skills/main/gallery/panel-route/step4-url-then-sync.png" alt="URL filled in, Sync button" width="480">
5. You land on **Discover**, filtered to the new marketplace (**Filter · 1**). Find **Nk data story** and press **Add**. Installed ones show **✓ Added**.
   <br><img src="https://raw.githubusercontent.com/NickkkLian/nickkk-skills/main/gallery/panel-route/step5-discover-add.png" alt="Discover list with Added and Add buttons" width="480">
6. Close the panel and start a new session.

To try it for one session without installing anything: `claude --plugin-dir ./nk-data-story` from a clone.

### 4 · OpenAI Codex CLI

```bash
git clone https://github.com/NickkkLian/nk-data-story.git ~/.agents/skills/nk-data-story
```

1. Run the command above (for one project only, clone into `.agents/skills/nk-data-story` inside that project).
2. Start a new Codex session.
3. Check it loaded, without spending a model call: `codex debug prompt-input | grep -o -- '- nk-data-story[a-z0-9:-]*' | sort -u` prints `- nk-data-story:nk-data-story:`. Codex adds the `nk-data-story:` prefix because this repository also carries a Claude Code plugin manifest. Ask for the task and the skill triggers on its own, or type `$` and pick it from the list.

## Compatibility

| Agent | Tested | What was checked |
|---|---|---|
| Claude Code (CLI 2.1.173, macOS) | yes | In a fresh project with an isolated Claude config, inside a macOS sandbox that blocked reading the tester's ~/.claude folder (settings, session history, memory), Desktop, Documents and Downloads, SSH keys and git identity, a plain request that never names the skill triggered it and it ran its bundled script. The route 2 plugin commands were also run from a shell with an isolated config: marketplace add, install, list. Here the request was a year of till exports with the question "what does it say"; the run profiled the file, wrote report.json and rendered the page. scripts/report_check.py reports 0 errors and 0 warnings on the report it wrote, which names the decision it informs, cites every number as a computed figure and lists what the data cannot answer. |
| OpenAI Codex CLI (0.154.0-alpha.6.2, gpt-5.6-sol, low reasoning, macOS) | yes | Copied into `~/.agents/skills` of a temporary home (the folder route 4 clones into), in a fresh project, without the user's Codex config. From a plain request that never names the skill, Codex read SKILL.md, ran `scripts/profile.py`, wrote report.json, checked it with `scripts/report_check.py` and rendered the page with `scripts/render.py`; re-checked here against the same input file, its report reports 0 errors and 0 warnings and the sha256 it pinned matches the file. |
| Cursor, Gemini CLI | no | Not tested. Their documentation says both read `~/.agents/skills`, the folder route 4 clones into; Gemini CLI asks before it activates a skill. |

In this skill's Codex run, every call into the skill folder's scripts/ used that folder's absolute path. Route 4 was checked for this repository: cloned from GitHub into a temporary home's `~/.agents/skills`, it was listed by the step 3 command. This skill's frontmatter uses only name, description, license and metadata.

## Verify

```bash
python3 scripts/datafile.py --selftest
python3 scripts/profile.py --selftest
python3 scripts/render.py --selftest
python3 scripts/report_check.py --selftest
```

Python 3.9+, standard library only. Before publishing, every rule line of report_check.py (the checks D01–D10)
was broken on purpose, one at a time, in a sandbox copy; each break turned the self-test red without a
traceback, and the unmutated control stayed green. datafile.py, profile.py and render.py have self-tests of
their own.

## Limits

- Reads CSV (UTF-8, cp1252 as a fallback; delimiter guessed among comma, semicolon, tab, pipe) and XLSX read-only: the value saved in each cell is read, formulas are not recalculated. A workbook that unzips to more than 200 MB, or whose XML declares a DOCTYPE, is refused. The whole table is held in memory.
- Numbers with a decimal comma (1.234,56) stay text on purpose: guessing the decimal mark silently changes every sum. Dates like 03/04/2025 are read only when another cell in the column settles the day/month order.
- The checks read the plan's structure. A report with zero findings can still answer the wrong question or phrase a claim more strongly than its figures allow; the person reading the page is the last check.
- No statistics: small samples are flagged, not modelled, and a change between two periods is not a trend.
- The example data is invented (a fictional bakery, seed 7), and marked as synthetic on its page.

## License

MIT. Read a script before letting it run in your environment.
