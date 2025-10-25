# litdb fromtext Command

## Overview
The `fromtext` command allows you to paste text containing academic references and automatically extract and add them to your litdb database.

## Usage

```bash
litdb fromtext "TEXT_WITH_REFERENCES" [OPTIONS]
```

## Options
- `--references` - Also add references from matched papers
- `--related` - Also add related papers
- `--citing` - Also add citing papers
- `--model TEXT` - Specify which LLM model to use (default: from config)

## How It Works

1. **LLM Parsing**: Uses an LLM (via litellm) to extract structured reference information from the text
2. **DOI Detection**: If a DOI is found in the parsed reference, it's used directly
3. **CrossRef Matching**: For references without DOIs, searches CrossRef API to find matches
4. **Confidence Scoring**: Automatically adds high-confidence matches (>0.85 similarity + year match)
5. **User Confirmation**: Prompts for confirmation on lower-confidence matches
6. **Database Addition**: Adds all confirmed references to litdb using the existing `add_work()` function

## Examples

### Basic usage with DOI
```bash
litdb fromtext "Kitchin, Examples of Effective Data Sharing in Scientific Publishing, ACS Catalysis, 2015, DOI: 10.1021/acscatal.5b00538"
```

### Multiple references from pasted text
```bash
litdb fromtext "Recent work by Smith et al. (Nature, 2020) showed...
Another study by Jones (Science, 2019) demonstrated..."
```

### With specific model
```bash
litdb fromtext "TEXT" --model "gpt-4o"
```

### With related papers
```bash
litdb fromtext "TEXT" --references --related --citing
```

## Supported Reference Formats

The LLM can parse various citation styles including:
- APA style
- Chicago style
- Numbered references
- Inline citations
- References with or without DOIs

## Configuration

The command uses your litdb configuration (`litdb.toml`):
- Default LLM model from `[llm]` section
- CrossRef API queries (no authentication required)
- Requires appropriate API keys in environment for non-ollama models

## Requirements

- LLM access (ollama, OpenAI, Anthropic, etc.) - configured via litellm
- Internet connection for CrossRef API
- Existing litdb database

## Notes

- The LLM may occasionally parse references imperfectly, especially with garbled text from PDFs
- CrossRef matching uses fuzzy string matching - review low-confidence matches carefully
- References that cannot be matched will be reported but skipped
- The command respects the same flags as `litdb add` for adding related works
